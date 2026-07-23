import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import PurePath
from uuid import UUID

from anyio import to_thread
from sqlalchemy.ext.asyncio import AsyncSession

from novel_platform.application.access import LibraryAccessScope
from novel_platform.application.books.commands import CreateBook
from novel_platform.application.books.service import BookService
from novel_platform.application.editions.commands import CreateEdition
from novel_platform.application.editions.service import EditionService
from novel_platform.application.errors import ApplicationError
from novel_platform.application.library.commands import CommitImport
from novel_platform.application.library.filenames import sanitize_filename
from novel_platform.application.library.policy import LibraryResourcePolicy
from novel_platform.application.library.storage import FileStorage, StorageError
from novel_platform.application.preferences.service import PreferenceService
from novel_platform.application.series.service import SeriesService
from novel_platform.domain.editions.models import CreationMethod, EditionStatus
from novel_platform.domain.errors import DomainRuleViolation
from novel_platform.domain.library.models import (
    FileFormat,
    ImportOperation,
    ImportStatus,
    StoredFilePurpose,
)
from novel_platform.infrastructure.database.models import (
    BookEditionModel,
    BookModel,
    EditionFileModel,
    LibraryImportModel,
    StoredFileModel,
)
from novel_platform.infrastructure.repositories.library import LibraryRepository

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class CommittedImport:
    library_import: LibraryImportModel
    book: BookModel
    edition: BookEditionModel


@dataclass(frozen=True, slots=True)
class _PendingAsset:
    temporary_key: str
    original_filename: str
    media_type: str
    file_format: FileFormat
    purpose: StoredFilePurpose
    size_bytes: int
    sha256: str


class ImportCommitService:
    def __init__(self, session: AsyncSession, storage: FileStorage) -> None:
        self.session = session
        self.storage = storage
        self.library = LibraryRepository(session)
        self.books = BookService(session)
        self.editions = EditionService(session)
        self.preferences = PreferenceService(session)
        self.series = SeriesService(session)
        self.policy = LibraryResourcePolicy(session)

    async def commit(
        self,
        *,
        scope: LibraryAccessScope,
        import_id: UUID,
        command: CommitImport,
    ) -> CommittedImport:
        self.policy.require_upload_capability(scope)
        owner_user_id = scope.owner_user_id
        library_import = await self.library.get_import(
            owner_user_id,
            import_id,
            for_update=True,
        )
        if library_import is None:
            raise ApplicationError("upload_not_found", "上传记录不存在。", status_code=404)
        self.policy.require_import_access(scope, library_import)
        if library_import.status is ImportStatus.SUCCEEDED:
            raise ApplicationError(
                "upload_already_committed", "该上传已经完成导入。", status_code=409
            )
        if library_import.status is not ImportStatus.READY:
            raise ApplicationError(
                "upload_not_ready", "上传尚未通过校验，不能提交。", status_code=409
            )
        self._validate_command(library_import, command)
        await self._validate_actor_command(scope, library_import, command)
        try:
            assets = await self._prepare_assets(library_import, command)
        except StorageError as exc:
            raise ApplicationError(
                "file_storage_error", "文件存储失败，请稍后重试。", status_code=500
            ) from exc
        moved: list[tuple[_PendingAsset, str]] = []
        unselected_temporary_keys = self._unselected_temporary_keys(library_import, assets)
        old_physical_keys: list[str] = []
        try:
            for asset in assets:
                storage_key = await to_thread.run_sync(
                    self.storage.commit_temporary, asset.temporary_key
                )
                moved.append((asset, storage_key))

            stored_files: dict[StoredFilePurpose, StoredFileModel] = {}
            for asset, storage_key in moved:
                stored_file = StoredFileModel(
                    owner_user_id=owner_user_id,
                    created_by_user_id=scope.viewer_user_id,
                    storage_key=storage_key,
                    original_filename=asset.original_filename,
                    media_type=asset.media_type,
                    file_format=asset.file_format,
                    purpose=asset.purpose,
                    size_bytes=asset.size_bytes,
                    sha256=asset.sha256,
                )
                await self.library.add_stored_file(stored_file)
                stored_files[asset.purpose] = stored_file

            book, edition = await self._apply_operation(
                owner_user_id=owner_user_id,
                scope=scope,
                library_import=library_import,
                command=command,
                stored_files=stored_files,
            )
            old_physical_keys = await self._apply_cover(
                book=book,
                stored_files=stored_files,
            )
            book.updated_at = datetime.now(UTC)
            library_import.status = ImportStatus.SUCCEEDED
            library_import.target_book_id = book.id
            library_import.target_edition_id = edition.id
            library_import.stored_file_id = stored_files[StoredFilePurpose.EDITION_SOURCE].id
            library_import.temporary_storage_key = None
            library_import.normalized_temporary_storage_key = None
            library_import.cover_temporary_storage_key = None
            library_import.cover_thumbnail_temporary_storage_key = None
            library_import.error_code = None
            library_import.error_message = None
            library_import.completed_at = datetime.now(UTC)
            await self.session.commit()
        except StorageError as exc:
            await self.session.rollback()
            await self._restore_moved(moved)
            raise ApplicationError(
                "file_storage_error", "文件存储失败，请稍后重试。", status_code=500
            ) from exc
        except Exception:
            await self.session.rollback()
            await self._restore_moved(moved)
            raise

        for key in unselected_temporary_keys:
            try:
                await to_thread.run_sync(self.storage.delete_temporary, key)
            except StorageError:
                logger.warning("Could not delete an unused import temporary object")
        for key in old_physical_keys:
            try:
                await to_thread.run_sync(self.storage.delete_file, key)
            except StorageError:
                logger.warning("Could not delete an unreferenced cover object")
        return CommittedImport(library_import=library_import, book=book, edition=edition)

    async def record_expected_failure(
        self,
        *,
        scope: LibraryAccessScope,
        import_id: UUID,
        error: ApplicationError | DomainRuleViolation,
    ) -> None:
        await self.session.rollback()
        library_import = await self.library.get_import(scope.owner_user_id, import_id)
        if library_import is None or library_import.status is not ImportStatus.READY:
            return
        self.policy.require_import_access(scope, library_import)
        if self._is_terminal_commit_error(library_import, error):
            library_import.status = ImportStatus.FAILED
        library_import.error_code = error.code
        library_import.error_message = error.message
        library_import.completed_at = datetime.now(UTC)
        await self.session.commit()

    async def record_unexpected_failure(
        self,
        *,
        scope: LibraryAccessScope,
        import_id: UUID,
    ) -> None:
        try:
            await self.session.rollback()
            library_import = await self.library.get_import(scope.owner_user_id, import_id)
            if library_import is None or library_import.status is not ImportStatus.READY:
                return
            self.policy.require_import_access(scope, library_import)
            library_import.status = ImportStatus.FAILED
            library_import.error_code = "internal_error"
            library_import.error_message = "导入提交失败，请联系管理员。"
            library_import.completed_at = datetime.now(UTC)
            await self.session.commit()
        except Exception:
            await self.session.rollback()
            logger.exception("Could not persist an unexpected import commit failure")

    @staticmethod
    def _is_terminal_commit_error(
        library_import: LibraryImportModel,
        error: ApplicationError | DomainRuleViolation,
    ) -> bool:
        if error.code == "file_integrity_error":
            return True
        if error.code == "book_not_found" and library_import.target_book_id is not None:
            return True
        return (
            error.code == "edition_not_found"
            and library_import.operation is ImportOperation.REPLACE_EDITION_FILE
        )

    async def _prepare_assets(
        self,
        library_import: LibraryImportModel,
        command: CommitImport,
    ) -> list[_PendingAsset]:
        if library_import.file_format not in {FileFormat.EPUB, FileFormat.TXT}:
            raise ApplicationError("unsupported_file_format", "上传格式不受支持。", status_code=422)
        source_key = library_import.temporary_storage_key
        if source_key is None:
            raise ApplicationError("file_integrity_error", "临时文件不存在。", status_code=409)
        source = await self._asset(
            key=source_key,
            original_filename=library_import.original_filename,
            media_type=(
                "application/epub+zip"
                if library_import.file_format is FileFormat.EPUB
                else "text/plain"
            ),
            file_format=library_import.file_format,
            purpose=StoredFilePurpose.EDITION_SOURCE,
        )
        if source.size_bytes != library_import.size_bytes or source.sha256 != library_import.sha256:
            raise ApplicationError(
                "file_integrity_error", "临时文件完整性校验失败。", status_code=409
            )
        assets = [source]
        if library_import.normalized_temporary_storage_key:
            stem = PurePath(library_import.original_filename).stem or "normalized"
            assets.append(
                await self._asset(
                    key=library_import.normalized_temporary_storage_key,
                    original_filename=sanitize_filename(f"{stem}.utf8.txt"),
                    media_type="text/plain; charset=utf-8",
                    file_format=FileFormat.TXT,
                    purpose=StoredFilePurpose.NORMALIZED_TEXT,
                )
            )
        use_cover = library_import.operation is not ImportOperation.REPLACE_EDITION_FILE and (
            command.use_extracted_cover
            if command.use_extracted_cover is not None
            else library_import.operation is ImportOperation.CREATE_BOOK
        )
        if (
            use_cover
            and library_import.cover_temporary_storage_key
            and library_import.cover_thumbnail_temporary_storage_key
            and library_import.cover_file_format
            and library_import.cover_filename
            and library_import.cover_media_type
        ):
            assets.append(
                await self._asset(
                    key=library_import.cover_temporary_storage_key,
                    original_filename=library_import.cover_filename,
                    media_type=library_import.cover_media_type,
                    file_format=library_import.cover_file_format,
                    purpose=StoredFilePurpose.BOOK_COVER,
                )
            )
            assets.append(
                await self._asset(
                    key=library_import.cover_thumbnail_temporary_storage_key,
                    original_filename="cover-thumbnail.jpg",
                    media_type="image/jpeg",
                    file_format=FileFormat.JPEG,
                    purpose=StoredFilePurpose.COVER_THUMBNAIL,
                )
            )
        return assets

    async def _asset(
        self,
        *,
        key: str,
        original_filename: str,
        media_type: str,
        file_format: FileFormat,
        purpose: StoredFilePurpose,
    ) -> _PendingAsset:
        exists = await to_thread.run_sync(self.storage.temporary_exists, key)
        if not exists:
            raise ApplicationError("file_integrity_error", "临时文件不存在。", status_code=409)
        path = self.storage.temporary_path(key)
        size_bytes = (await to_thread.run_sync(path.stat)).st_size
        sha256 = await to_thread.run_sync(self.storage.calculate_temporary_checksum, key)
        return _PendingAsset(
            temporary_key=key,
            original_filename=sanitize_filename(original_filename),
            media_type=media_type,
            file_format=file_format,
            purpose=purpose,
            size_bytes=size_bytes,
            sha256=sha256,
        )

    async def _apply_operation(
        self,
        *,
        owner_user_id: UUID,
        scope: LibraryAccessScope,
        library_import: LibraryImportModel,
        command: CommitImport,
        stored_files: dict[StoredFilePurpose, StoredFileModel],
    ) -> tuple[BookModel, BookEditionModel]:
        if library_import.operation is ImportOperation.REPLACE_EDITION_FILE:
            if library_import.target_book_id is None or library_import.target_edition_id is None:
                raise ApplicationError("edition_not_found", "Edition 不存在。", status_code=404)
            book = await self.books.get(library_import.target_book_id, owner_user_id)
            edition = await self.editions.get(
                book.id,
                owner_user_id,
                library_import.target_edition_id,
                for_update=True,
            )
            await self.policy.require_edition_replace(scope, edition)
            current = await self.library.get_current_edition_file(edition.id)
            if current:
                current.edition_file.is_current = False
                await self.session.flush()
            file_revision = await self.library.next_file_revision(edition.id)
            edition.updated_at = datetime.now(UTC)
        else:
            if library_import.operation is ImportOperation.CREATE_BOOK:
                book = await self.books.create(
                    CreateBook(
                        canonical_title=command.canonical_title or "",
                        canonical_author=command.canonical_author,
                        description=command.description,
                        metadata={
                            "source_metadata": dict(library_import.metadata_preview),
                            **command.book_metadata,
                        },
                    ),
                    owner_user_id,
                    created_by_user_id=scope.viewer_user_id,
                    commit=False,
                )
                if command.series_id is not None:
                    await self.series.add_new_book(owner_user_id, command.series_id, book)
            else:
                if library_import.target_book_id is None:
                    raise ApplicationError("book_not_found", "Book 不存在。", status_code=404)
                book = await self.books.get(library_import.target_book_id, owner_user_id)
            content_role = command.content_role
            if content_role is None:
                raise ApplicationError(
                    "validation_error", "必须选择 Edition 类型。", status_code=422
                )
            edition = await self.editions.create(
                book.id,
                owner_user_id,
                CreateEdition(
                    title=command.edition_title or "",
                    language=command.language or "",
                    content_role=content_role,
                    translation_origin=command.translation_origin,
                    creation_method=CreationMethod.UPLOADED,
                    source_edition_id=command.source_edition_id,
                    supersedes_edition_id=command.supersedes_edition_id,
                    status=command.edition_status,
                    metadata={
                        "source_metadata": dict(library_import.metadata_preview),
                        **command.edition_metadata,
                    },
                ),
                created_by_user_id=scope.viewer_user_id,
                commit=False,
            )
            file_revision = 1

        normalized = stored_files.get(StoredFilePurpose.NORMALIZED_TEXT)
        await self.library.add_edition_file(
            EditionFileModel(
                edition_id=edition.id,
                stored_file_id=stored_files[StoredFilePurpose.EDITION_SOURCE].id,
                normalized_stored_file_id=normalized.id if normalized is not None else None,
                revision=file_revision,
                is_current=True,
                text_encoding=library_import.text_encoding,
                content_item_count=library_import.content_item_count,
                extracted_metadata=dict(library_import.metadata_preview),
            )
        )
        if (
            command.set_preferred
            and library_import.operation is not ImportOperation.REPLACE_EDITION_FILE
        ):
            await self.preferences.update(
                owner_user_id,
                scope.viewer_user_id,
                book.id,
                {"preferred_edition_id": edition.id},
                readable_only=not scope.can_manage,
                commit=False,
            )
        return book, edition

    async def _apply_cover(
        self,
        *,
        book: BookModel,
        stored_files: dict[StoredFilePurpose, StoredFileModel],
    ) -> list[str]:
        cover = stored_files.get(StoredFilePurpose.BOOK_COVER)
        thumbnail = stored_files.get(StoredFilePurpose.COVER_THUMBNAIL)
        if cover is None or thumbnail is None:
            return []
        if (
            cover.owner_user_id != book.owner_user_id
            or thumbnail.owner_user_id != book.owner_user_id
        ):
            raise ApplicationError(
                "file_integrity_error",
                "封面文件所有权异常。",
                status_code=500,
            )
        old_files: list[StoredFileModel] = []
        for stored_file_id in (book.cover_file_id, book.cover_thumbnail_file_id):
            if stored_file_id is None:
                continue
            old_file = await self.library.get_stored_file(stored_file_id)
            if old_file is None or old_file.owner_user_id != book.owner_user_id:
                raise ApplicationError(
                    "file_integrity_error",
                    "现有封面文件所有权异常。",
                    status_code=500,
                )
            old_files.append(old_file)
        book.cover_file_id = cover.id
        book.cover_thumbnail_file_id = thumbnail.id
        await self.session.flush()
        physical_keys: list[str] = []
        for old_file in old_files:
            if await self.library.stored_file_is_referenced(old_file.id):
                continue
            physical_keys.append(old_file.storage_key)
            await self.session.delete(old_file)
        return physical_keys

    async def _restore_moved(self, moved: list[tuple[_PendingAsset, str]]) -> None:
        for asset, storage_key in reversed(moved):
            try:
                await to_thread.run_sync(
                    self.storage.restore_committed,
                    storage_key,
                    asset.temporary_key,
                )
            except StorageError:
                logger.warning("Could not restore a file after import transaction rollback")

    @staticmethod
    def _validate_command(
        library_import: LibraryImportModel,
        command: CommitImport,
    ) -> None:
        if library_import.operation is ImportOperation.REPLACE_EDITION_FILE:
            if command.series_id is not None:
                raise ApplicationError(
                    "validation_error",
                    "替换 Edition 文件时不能指定系列。",
                    status_code=422,
                )
            return
        if library_import.operation is not ImportOperation.CREATE_BOOK and command.series_id:
            raise ApplicationError(
                "validation_error",
                "只有创建新 Book 时才能通过导入指定系列。",
                status_code=422,
            )
        if library_import.operation is ImportOperation.CREATE_BOOK and not (
            command.canonical_title and command.canonical_title.strip()
        ):
            raise ApplicationError(
                "validation_error", "创建 Book 时必须填写书名。", status_code=422
            )
        if not command.edition_title or not command.edition_title.strip():
            raise ApplicationError("validation_error", "必须填写 Edition 名称。", status_code=422)
        if not command.language or not command.language.strip():
            raise ApplicationError("validation_error", "必须填写 Edition 语言。", status_code=422)
        if command.content_role is None:
            raise ApplicationError("validation_error", "必须选择 Edition 类型。", status_code=422)

    async def _validate_actor_command(
        self,
        scope: LibraryAccessScope,
        library_import: LibraryImportModel,
        command: CommitImport,
    ) -> None:
        self.policy.require_upload_capability(scope)
        if scope.can_manage:
            return
        forbidden: list[str] = []
        if command.series_id is not None:
            forbidden.append("series_id")
        if command.edition_status is not EditionStatus.READY:
            forbidden.append("edition_status")
        if forbidden:
            raise ApplicationError(
                "contributor_field_forbidden",
                "贡献者不能管理系列或版本发布状态。",
                status_code=403,
                details={"fields": forbidden},
            )

        if library_import.operation is ImportOperation.ADD_EDITION:
            if library_import.target_book_id is None:
                raise ApplicationError("book_not_found", "Book 不存在。", status_code=404)
            book = await self.books.repository.get_readable(
                library_import.target_book_id,
                scope.owner_user_id,
            )
            await self.policy.require_readable_book_for_upload(scope, book)
        elif library_import.operation is ImportOperation.REPLACE_EDITION_FILE:
            if library_import.target_edition_id is None:
                raise ApplicationError("edition_not_found", "Edition 不存在。", status_code=404)
            edition = await self.editions.editions.get_readable(
                scope.owner_user_id,
                library_import.target_edition_id,
            )
            if edition is None:
                raise ApplicationError("edition_not_found", "Edition 不存在。", status_code=404)
            await self.policy.require_edition_replace(scope, edition)

        for referenced_id in (
            command.source_edition_id,
            command.supersedes_edition_id,
        ):
            if referenced_id is None:
                continue
            referenced = await self.editions.editions.get_readable(
                scope.owner_user_id,
                referenced_id,
            )
            if referenced is None:
                raise ApplicationError(
                    "edition_not_found",
                    "引用的 Edition 不存在。",
                    status_code=404,
                )

    @staticmethod
    def _unselected_temporary_keys(
        library_import: LibraryImportModel,
        assets: list[_PendingAsset],
    ) -> list[str]:
        selected = {asset.temporary_key for asset in assets}
        return [
            key
            for key in (
                library_import.temporary_storage_key,
                library_import.normalized_temporary_storage_key,
                library_import.cover_temporary_storage_key,
                library_import.cover_thumbnail_temporary_storage_key,
            )
            if key is not None and key not in selected
        ]
