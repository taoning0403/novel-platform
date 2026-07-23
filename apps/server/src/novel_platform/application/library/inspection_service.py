import logging
import zipfile
from datetime import UTC, datetime
from functools import partial
from pathlib import PurePath
from typing import BinaryIO
from uuid import UUID

from anyio import to_thread
from sqlalchemy.ext.asyncio import AsyncSession

from novel_platform.application.errors import ApplicationError
from novel_platform.application.library.commands import InspectImport
from novel_platform.application.library.epub import inspect_epub
from novel_platform.application.library.filenames import sanitize_filename
from novel_platform.application.library.storage import (
    FileStorage,
    StorageError,
    StorageLimitExceeded,
)
from novel_platform.application.library.text import normalize_text
from novel_platform.config import Settings
from novel_platform.domain.library.models import FileFormat, ImportOperation, ImportStatus
from novel_platform.infrastructure.database.models import LibraryImportModel
from novel_platform.infrastructure.repositories.books import BookRepository
from novel_platform.infrastructure.repositories.editions import EditionRepository
from novel_platform.infrastructure.repositories.library import LibraryRepository

logger = logging.getLogger(__name__)


class ImportInspectionService:
    def __init__(
        self,
        session: AsyncSession,
        storage: FileStorage,
        settings: Settings,
    ) -> None:
        self.session = session
        self.storage = storage
        self.settings = settings
        self.books = BookRepository(session)
        self.editions = EditionRepository(session)
        self.library = LibraryRepository(session)

    async def inspect(
        self,
        *,
        owner_user_id: UUID,
        requested_by_user_id: UUID,
        command: InspectImport,
        stream: BinaryIO,
    ) -> LibraryImportModel:
        target_book_id, target_edition_id = await self._validate_target(
            owner_user_id=owner_user_id,
            command=command,
        )
        filename = sanitize_filename(command.filename)
        library_import = LibraryImportModel(
            owner_user_id=owner_user_id,
            requested_by_user_id=requested_by_user_id,
            status=ImportStatus.PENDING,
            operation=command.operation,
            original_filename=filename,
            submitted_media_type=(command.submitted_media_type or "")[:200] or None,
            target_book_id=target_book_id,
            target_edition_id=target_edition_id,
            metadata_preview={},
            warnings=[],
        )
        await self.library.add_import(library_import)
        await self.session.commit()
        library_import.status = ImportStatus.PROCESSING
        library_import.started_at = datetime.now(UTC)
        await self.session.commit()

        try:
            await to_thread.run_sync(stream.seek, 0)
            temporary = await to_thread.run_sync(
                partial(
                    self.storage.write_temporary,
                    stream,
                    max_bytes=self.settings.max_upload_bytes,
                )
            )
            library_import.temporary_storage_key = temporary.key
            library_import.size_bytes = temporary.size_bytes
            library_import.sha256 = temporary.sha256
            await self.session.commit()

            extension = PurePath(filename).suffix.lower()
            if extension == ".epub":
                await self._inspect_epub(library_import)
            elif extension == ".txt":
                await self._inspect_text(
                    library_import,
                    requested_encoding=command.requested_text_encoding,
                )
            else:
                raise ApplicationError(
                    "unsupported_file_format",
                    "仅支持 .epub 和 .txt 文件。",
                    status_code=422,
                )

            library_import.status = ImportStatus.READY
            library_import.completed_at = datetime.now(UTC)
            library_import.error_code = None
            library_import.error_message = None
            await self.session.commit()
            await self.session.refresh(library_import)
            return library_import
        except StorageLimitExceeded as exc:
            error = ApplicationError(
                "upload_too_large",
                "上传文件超过允许的大小。",
                status_code=413,
            )
            await self._record_failure(library_import, error)
            raise self._with_import_id(error, library_import.id) from exc
        except ApplicationError as exc:
            await self._record_failure(library_import, exc)
            raise self._with_import_id(exc, library_import.id) from exc
        except StorageError as exc:
            error = ApplicationError(
                "file_storage_error",
                "文件存储失败，请稍后重试。",
                status_code=500,
            )
            await self._record_failure(library_import, error)
            raise self._with_import_id(error, library_import.id) from exc
        except Exception as exc:
            logger.exception("Unexpected import inspection failure", exc_info=exc)
            error = ApplicationError(
                "file_storage_error",
                "文件处理失败，请稍后重试。",
                status_code=500,
            )
            await self._record_failure(library_import, error)
            raise self._with_import_id(error, library_import.id) from exc

    async def get(self, owner_user_id: UUID, import_id: UUID) -> LibraryImportModel:
        library_import = await self.library.get_import(owner_user_id, import_id)
        if library_import is None:
            raise ApplicationError("upload_not_found", "上传记录不存在。", status_code=404)
        return library_import

    async def delete(self, owner_user_id: UUID, import_id: UUID) -> None:
        library_import = await self.library.get_import(
            owner_user_id,
            import_id,
            for_update=True,
        )
        if library_import is None:
            raise ApplicationError("upload_not_found", "上传记录不存在。", status_code=404)
        if library_import.status is ImportStatus.SUCCEEDED:
            raise ApplicationError(
                "upload_already_committed",
                "已完成的导入记录不能作为临时上传删除。",
                status_code=409,
            )
        temporary_keys = self._temporary_keys(library_import)
        await self.session.delete(library_import)
        await self.session.commit()
        for key in temporary_keys:
            try:
                await to_thread.run_sync(self.storage.delete_temporary, key)
            except StorageError:
                logger.warning("Could not delete an import temporary object")

    async def _inspect_epub(self, library_import: LibraryImportModel) -> None:
        key = library_import.temporary_storage_key
        if key is None:
            raise ApplicationError("file_integrity_error", "临时文件不存在。", status_code=500)
        parsed = await to_thread.run_sync(
            partial(
                inspect_epub,
                self.storage.temporary_path(key),
                max_entry_count=self.settings.max_epub_entry_count,
                max_uncompressed_bytes=self.settings.max_epub_uncompressed_bytes,
                max_cover_bytes=self.settings.max_cover_bytes,
                max_cover_pixels=self.settings.max_cover_pixels,
            )
        )
        library_import.file_format = FileFormat.EPUB
        library_import.metadata_preview = parsed.metadata
        library_import.content_item_count = parsed.content_item_count
        library_import.warnings = parsed.warnings
        if parsed.cover:
            cover = await to_thread.run_sync(
                partial(
                    self.storage.write_temporary_bytes,
                    parsed.cover.content,
                    max_bytes=self.settings.max_cover_bytes,
                )
            )
            try:
                thumbnail = await to_thread.run_sync(
                    partial(
                        self.storage.write_temporary_bytes,
                        parsed.cover.thumbnail,
                        max_bytes=self.settings.max_cover_bytes,
                    )
                )
            except Exception:
                await to_thread.run_sync(self.storage.delete_temporary, cover.key)
                raise
            library_import.cover_temporary_storage_key = cover.key
            library_import.cover_thumbnail_temporary_storage_key = thumbnail.key
            library_import.cover_filename = parsed.cover.filename
            library_import.cover_media_type = parsed.cover.media_type
            library_import.cover_file_format = parsed.cover.file_format

    async def _inspect_text(
        self,
        library_import: LibraryImportModel,
        *,
        requested_encoding: str,
    ) -> None:
        key = library_import.temporary_storage_key
        if key is None:
            raise ApplicationError("file_integrity_error", "临时文件不存在。", status_code=500)
        source_path = self.storage.temporary_path(key)
        if await to_thread.run_sync(zipfile.is_zipfile, source_path):
            raise ApplicationError(
                "unsupported_file_format",
                "文件内容与 TXT 扩展名不一致。",
                status_code=422,
            )
        normalized_key = await to_thread.run_sync(self.storage.allocate_temporary)
        normalized_path = self.storage.temporary_path(normalized_key)
        inferred_title = PurePath(library_import.original_filename).stem or "未命名作品"
        try:
            parsed = await to_thread.run_sync(
                partial(
                    normalize_text,
                    source_path,
                    normalized_path,
                    requested_encoding=requested_encoding,
                    inferred_title=inferred_title,
                )
            )
        except Exception:
            await to_thread.run_sync(self.storage.delete_temporary, normalized_key)
            raise
        library_import.file_format = FileFormat.TXT
        library_import.normalized_temporary_storage_key = normalized_key
        library_import.text_encoding = parsed.encoding
        library_import.content_item_count = parsed.content_item_count
        library_import.metadata_preview = parsed.metadata

    async def _validate_target(
        self,
        *,
        owner_user_id: UUID,
        command: InspectImport,
    ) -> tuple[UUID | None, UUID | None]:
        if command.operation is ImportOperation.CREATE_BOOK:
            return None, None
        if command.operation is ImportOperation.ADD_EDITION:
            if command.target_book_id is None:
                raise ApplicationError(
                    "validation_error", "添加 Edition 时必须选择 Book。", status_code=422
                )
            if await self.books.get(command.target_book_id, owner_user_id) is None:
                raise ApplicationError("book_not_found", "Book 不存在。", status_code=404)
            return command.target_book_id, None
        if command.target_edition_id is None:
            raise ApplicationError(
                "validation_error", "替换文件时必须选择 Edition。", status_code=422
            )
        edition = await self.editions.get_for_owner(owner_user_id, command.target_edition_id)
        if edition is None:
            raise ApplicationError("edition_not_found", "Edition 不存在。", status_code=404)
        if command.target_book_id is not None and command.target_book_id != edition.book_id:
            raise ApplicationError("edition_not_found", "Edition 不存在。", status_code=404)
        return edition.book_id, edition.id

    async def _record_failure(
        self, library_import: LibraryImportModel, error: ApplicationError
    ) -> None:
        try:
            library_import.status = ImportStatus.FAILED
            library_import.error_code = error.code
            library_import.error_message = error.message
            library_import.completed_at = datetime.now(UTC)
            await self.session.commit()
        except Exception:
            await self.session.rollback()
            logger.exception("Could not persist import failure state")

    @staticmethod
    def _with_import_id(error: ApplicationError, import_id: UUID) -> ApplicationError:
        return ApplicationError(
            error.code,
            error.message,
            status_code=error.status_code,
            details={**error.details, "import_id": str(import_id)},
            headers=error.headers,
        )

    @staticmethod
    def _temporary_keys(library_import: LibraryImportModel) -> list[str]:
        return [
            key
            for key in (
                library_import.temporary_storage_key,
                library_import.normalized_temporary_storage_key,
                library_import.cover_temporary_storage_key,
                library_import.cover_thumbnail_temporary_storage_key,
            )
            if key is not None
        ]
