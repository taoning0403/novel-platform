import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from anyio import to_thread
from sqlalchemy import delete, update
from sqlalchemy.ext.asyncio import AsyncSession

from novel_platform.application.access import LibraryAccessScope
from novel_platform.application.errors import ApplicationError
from novel_platform.application.library.policy import LibraryResourcePolicy
from novel_platform.application.library.storage import FileStorage, StorageError
from novel_platform.infrastructure.database.models import (
    BookEditionModel,
    EditionTranslationRunModel,
    ReadingProgressModel,
    StoredFileModel,
    UserBookPreferenceModel,
)
from novel_platform.infrastructure.repositories.books import BookRepository
from novel_platform.infrastructure.repositories.editions import EditionRepository
from novel_platform.infrastructure.repositories.library import EditionFileRecord, LibraryRepository

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class DownloadableFile:
    stored_file: StoredFileModel
    storage: FileStorage


class LibraryFileService:
    def __init__(self, session: AsyncSession, storage: FileStorage) -> None:
        self.session = session
        self.storage = storage
        self.books = BookRepository(session)
        self.editions = EditionRepository(session)
        self.library = LibraryRepository(session)
        self.policy = LibraryResourcePolicy(session)

    async def edition_download(self, owner_user_id: UUID, edition_id: UUID) -> DownloadableFile:
        edition = await self.editions.get_for_owner(owner_user_id, edition_id)
        if edition is None:
            raise ApplicationError("edition_not_found", "Edition 不存在。", status_code=404)
        record = await self.library.get_current_edition_file(edition.id)
        if record is None:
            raise ApplicationError("file_not_found", "Edition 尚未关联文件。", status_code=404)
        if record.stored_file.owner_user_id != owner_user_id:
            raise ApplicationError(
                "file_integrity_error", "Edition 文件所有权异常。", status_code=500
            )
        await self._ensure_integrity(record.stored_file, message="Edition 文件缺失或损坏。")
        return DownloadableFile(record.stored_file, self.storage)

    async def book_cover(
        self,
        owner_user_id: UUID,
        book_id: UUID,
        *,
        thumbnail: bool,
    ) -> DownloadableFile:
        book = await self.books.get(book_id, owner_user_id)
        if book is None:
            raise ApplicationError("book_not_found", "Book 不存在。", status_code=404)
        stored_file_id = book.cover_thumbnail_file_id if thumbnail else book.cover_file_id
        if stored_file_id is None:
            raise ApplicationError("file_not_found", "Book 没有封面。", status_code=404)
        stored_file = await self.library.get_stored_file(stored_file_id)
        if stored_file is None or stored_file.owner_user_id != owner_user_id:
            raise ApplicationError("file_integrity_error", "封面文件所有权异常。", status_code=500)
        await self._ensure_integrity(stored_file, message="封面文件缺失或损坏。")
        return DownloadableFile(stored_file, self.storage)

    async def _ensure_integrity(self, stored_file: StoredFileModel, *, message: str) -> None:
        try:
            actual_sha256 = await to_thread.run_sync(
                self.storage.calculate_checksum,
                stored_file.storage_key,
            )
        except StorageError as exc:
            raise ApplicationError("file_integrity_error", message, status_code=500) from exc
        if actual_sha256 != stored_file.sha256:
            raise ApplicationError("file_integrity_error", message, status_code=500)

    async def delete_edition(
        self,
        *,
        scope: LibraryAccessScope,
        book_id: UUID,
        edition_id: UUID,
    ) -> None:
        owner_user_id = scope.owner_user_id
        book = await self.books.get(book_id, owner_user_id)
        if book is None:
            raise ApplicationError("book_not_found", "Book 不存在。", status_code=404)
        edition = await self.editions.get_for_book(book.id, edition_id, for_update=True)
        if edition is None:
            raise ApplicationError("edition_not_found", "Edition 不存在。", status_code=404)
        await self.policy.require_edition_delete(scope, edition)
        dependents = await self.editions.dependents(edition.id)
        if dependents:
            raise ApplicationError(
                "edition_dependency_conflict",
                "其他 Edition 仍依赖该版本，请先解除 source 或 supersedes 关系。",
                status_code=409,
            )
        records = await self.library.edition_file_records(edition.id)
        self._require_owned_files(owner_user_id, records)
        await self.session.execute(
            update(UserBookPreferenceModel)
            .where(
                UserBookPreferenceModel.book_id == book.id,
                UserBookPreferenceModel.preferred_edition_id == edition.id,
            )
            .values(preferred_edition_id=None, updated_at=datetime.now(UTC))
        )
        await self.session.execute(
            update(UserBookPreferenceModel)
            .where(
                UserBookPreferenceModel.book_id == book.id,
                UserBookPreferenceModel.last_opened_edition_id == edition.id,
            )
            .values(last_opened_edition_id=None, updated_at=datetime.now(UTC))
        )
        await self.session.execute(
            delete(ReadingProgressModel).where(ReadingProgressModel.edition_id == edition.id)
        )
        for record in records:
            await self.session.delete(record.edition_file)
        await self.session.flush()
        await self.session.delete(edition)
        book.updated_at = datetime.now(UTC)
        await self.session.flush()
        physical_keys = await self._delete_unreferenced_stored_files(records)
        await self.session.commit()
        await self._delete_physical_files(physical_keys)

    async def delete_book(self, *, scope: LibraryAccessScope, book_id: UUID) -> None:
        owner_user_id = scope.owner_user_id
        book = await self.books.get(book_id, owner_user_id)
        if book is None:
            raise ApplicationError("book_not_found", "Book 不存在。", status_code=404)
        await self.policy.require_book_delete(scope, book)
        editions = await self.books.editions(book.id)
        records: list[EditionFileRecord] = []
        for edition in editions:
            records.extend(await self.library.edition_file_records(edition.id))
        cover_files: list[StoredFileModel] = []
        for stored_file_id in (book.cover_file_id, book.cover_thumbnail_file_id):
            if stored_file_id is None:
                continue
            stored_file = await self.library.get_stored_file(stored_file_id)
            if stored_file is None or stored_file.owner_user_id != owner_user_id:
                raise ApplicationError(
                    "file_integrity_error",
                    "Book 文件所有权异常。",
                    status_code=500,
                )
            cover_files.append(stored_file)
        self._require_owned_files(owner_user_id, records)
        await self.session.execute(
            delete(UserBookPreferenceModel).where(
                UserBookPreferenceModel.book_id == book.id,
            )
        )
        await self.session.execute(
            delete(EditionTranslationRunModel).where(EditionTranslationRunModel.book_id == book.id)
        )
        if editions:
            edition_ids = [edition.id for edition in editions]
            await self.session.execute(
                update(BookEditionModel)
                .where(BookEditionModel.id.in_(edition_ids))
                .values(source_edition_id=None, supersedes_edition_id=None)
            )
        for record in records:
            await self.session.delete(record.edition_file)
        await self.session.flush()
        for edition in editions:
            await self.session.delete(edition)
        book.cover_file_id = None
        book.cover_thumbnail_file_id = None
        await self.session.flush()
        await self.session.delete(book)
        await self.session.flush()
        physical_keys = await self._delete_unreferenced_stored_files(records)
        for stored_file in cover_files:
            if not await self.library.stored_file_is_referenced(stored_file.id):
                physical_keys.append(stored_file.storage_key)
                await self.session.delete(stored_file)
        await self.session.commit()
        await self._delete_physical_files(physical_keys)

    async def _delete_unreferenced_stored_files(
        self, records: list[EditionFileRecord]
    ) -> list[str]:
        stored_files: dict[UUID, StoredFileModel] = {}
        for record in records:
            stored_files[record.stored_file.id] = record.stored_file
            if record.normalized_file:
                stored_files[record.normalized_file.id] = record.normalized_file
        physical_keys: list[str] = []
        for stored_file in stored_files.values():
            if not await self.library.stored_file_is_referenced(stored_file.id):
                physical_keys.append(stored_file.storage_key)
                await self.session.delete(stored_file)
        return physical_keys

    @staticmethod
    def _require_owned_files(
        owner_user_id: UUID,
        records: list[EditionFileRecord],
    ) -> None:
        for record in records:
            if record.stored_file.owner_user_id != owner_user_id or (
                record.normalized_file is not None
                and record.normalized_file.owner_user_id != owner_user_id
            ):
                raise ApplicationError(
                    "file_integrity_error",
                    "Edition 文件所有权异常。",
                    status_code=500,
                )

    async def _delete_physical_files(self, storage_keys: list[str]) -> None:
        for storage_key in set(storage_keys):
            try:
                await to_thread.run_sync(self.storage.delete_file, storage_key)
            except StorageError:
                logger.warning("Could not delete an unreferenced library file")
