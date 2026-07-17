import argparse
import asyncio
from datetime import UTC, datetime, timedelta
from functools import partial

from anyio import to_thread
from sqlalchemy import select

from novel_platform.application.library.cleanup import deletable_expired_keys
from novel_platform.config import get_settings
from novel_platform.domain.library.models import ImportStatus
from novel_platform.infrastructure.database.models import LibraryImportModel, StoredFileModel
from novel_platform.infrastructure.database.session import engine, session_factory
from novel_platform.infrastructure.storage.local import LocalFileStorage


def arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Expire stale imports and report or remove unreferenced library files."
    )
    parser.add_argument("--older-than-hours", type=int, default=None)
    parser.add_argument(
        "--delete-orphans",
        action="store_true",
        help="Delete permanent files that have no stored_files database row.",
    )
    return parser.parse_args()


async def main() -> None:
    options = arguments()
    settings = get_settings()
    hours = (
        options.older_than_hours
        if options.older_than_hours is not None
        else settings.library_temporary_ttl_hours
    )
    if hours < 1:
        raise SystemExit("--older-than-hours must be positive")
    cutoff = datetime.now(UTC) - timedelta(hours=hours)
    storage = LocalFileStorage(settings.library_storage_root)

    expired_keys: set[str] = set()
    async with session_factory() as session:
        stale = list(
            (
                await session.scalars(
                    select(LibraryImportModel)
                    .where(
                        LibraryImportModel.status.in_(
                            [
                                ImportStatus.PENDING,
                                ImportStatus.PROCESSING,
                                ImportStatus.READY,
                                ImportStatus.FAILED,
                            ]
                        ),
                        LibraryImportModel.created_at < cutoff,
                    )
                    .with_for_update(skip_locked=True)
                )
            ).all()
        )
        for library_import in stale:
            expired_keys.update(
                key
                for key in (
                    library_import.temporary_storage_key,
                    library_import.normalized_temporary_storage_key,
                    library_import.cover_temporary_storage_key,
                    library_import.cover_thumbnail_temporary_storage_key,
                )
                if key is not None
            )
            if library_import.status is not ImportStatus.FAILED:
                library_import.status = ImportStatus.FAILED
                library_import.error_code = "upload_expired"
                library_import.error_message = "上传预览已过期，请重新上传。"
                library_import.completed_at = datetime.now(UTC)
            library_import.temporary_storage_key = None
            library_import.normalized_temporary_storage_key = None
            library_import.cover_temporary_storage_key = None
            library_import.cover_thumbnail_temporary_storage_key = None
        await session.commit()

        referenced = set(await session.scalars(select(StoredFileModel.storage_key)))
        remaining_temporary_keys: set[str] = set()
        remaining_rows = await session.execute(
            select(
                LibraryImportModel.temporary_storage_key,
                LibraryImportModel.normalized_temporary_storage_key,
                LibraryImportModel.cover_temporary_storage_key,
                LibraryImportModel.cover_thumbnail_temporary_storage_key,
            )
        )
        for row in remaining_rows:
            remaining_temporary_keys.update(key for key in row if key is not None)

    expired_files_to_delete = deletable_expired_keys(expired_keys, remaining_temporary_keys)
    for key in expired_files_to_delete:
        await to_thread.run_sync(storage.delete_temporary, key)
    removed_untracked_temporary = await to_thread.run_sync(
        partial(
            storage.cleanup_temporary_files,
            older_than=cutoff,
            preserve_keys=remaining_temporary_keys,
        ),
    )
    physical = await to_thread.run_sync(storage.list_storage_keys)
    orphans = physical - referenced
    old_physical = await to_thread.run_sync(
        partial(storage.list_storage_keys_older_than, older_than=cutoff)
    )
    deletable_orphans = orphans & old_physical
    missing = referenced - physical
    if options.delete_orphans:
        for key in deletable_orphans:
            await to_thread.run_sync(storage.delete_file, key)

    await engine.dispose()
    print(f"expired_imports={len(stale)}")
    print(f"expired_import_files={len(expired_files_to_delete)}")
    print(f"expired_import_files_preserved={len(expired_keys - expired_files_to_delete)}")
    print(f"untracked_temporary_files_removed={removed_untracked_temporary}")
    print(f"permanent_orphans_reported={len(orphans)}")
    print(f"permanent_orphans_deleted={len(deletable_orphans) if options.delete_orphans else 0}")
    print(f"recent_orphans_deferred={len(orphans - old_physical)}")
    print(f"database_files_missing={len(missing)}")
    if missing:
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
