from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from anyio import to_thread
from sqlalchemy.ext.asyncio import AsyncSession

from novel_platform.application.errors import ApplicationError
from novel_platform.application.library.storage import FileStorage, StorageError
from novel_platform.application.preferences.service import PreferenceService
from novel_platform.application.reader.content import (
    ReaderPublication,
    ReaderResourceContent,
    ReaderSectionContent,
    build_epub_publication,
    build_text_publication,
    read_epub_resource,
    read_epub_section,
    read_text_section,
)
from novel_platform.config import Settings
from novel_platform.domain.library.models import FileFormat
from novel_platform.domain.reader.models import ReadingStatus
from novel_platform.infrastructure.database.models import (
    BookEditionModel,
    BookModel,
    ReaderSettingsModel,
    ReadingProgressModel,
)
from novel_platform.infrastructure.repositories.books import BookRepository
from novel_platform.infrastructure.repositories.editions import EditionRepository
from novel_platform.infrastructure.repositories.library import EditionFileRecord, LibraryRepository
from novel_platform.infrastructure.repositories.reader import ReaderRepository, RecentReadingRecord


@dataclass(frozen=True, slots=True)
class ReaderEditionRecord:
    edition: BookEditionModel
    file: EditionFileRecord
    progress: ReadingProgressModel | None


@dataclass(frozen=True, slots=True)
class OpenedReader:
    book: BookModel
    edition: BookEditionModel
    file: EditionFileRecord
    publication: ReaderPublication
    progress: ReadingProgressModel
    settings: ReaderSettingsModel
    editions: tuple[ReaderEditionRecord, ...]


class ReaderService:
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
        self.reader = ReaderRepository(session)
        self.preferences = PreferenceService(session)

    async def open(
        self,
        *,
        owner_user_id: UUID,
        viewer_user_id: UUID,
        device_id: UUID,
        edition_id: UUID,
        readable_only: bool,
    ) -> OpenedReader:
        edition, file_record = await self._readable_edition(
            owner_user_id, edition_id, readable_only=readable_only
        )
        publication = await self._publication(file_record)
        book = await self.books.get(edition.book_id, owner_user_id)
        if book is None:
            raise ApplicationError("book_not_found", "Book 不存在。", status_code=404)
        now = datetime.now(UTC)
        await self.reader.create_progress_if_missing(
            user_id=viewer_user_id,
            edition_id=edition.id,
            status=ReadingStatus.READING,
            section_id=publication.sections[0].id,
            block_id=None,
            section_progress=0,
            overall_progress=0,
            edition_file_revision=file_record.edition_file.revision,
            updated_device_id=device_id,
            at=now,
        )
        progress = await self.reader.get_progress(viewer_user_id, edition.id, for_update=True)
        if progress is None:
            raise RuntimeError("reading progress upsert did not produce a row")
        progress.last_read_at = now
        if progress.status is ReadingStatus.NOT_STARTED:
            progress.status = ReadingStatus.READING
            progress.version += 1
            progress.updated_device_id = device_id
            progress.updated_at = now
        reader_settings = await self._settings(viewer_user_id)
        await self.preferences.update(
            viewer_user_id,
            owner_user_id,
            book.id,
            {"last_opened_edition_id": edition.id},
            readable_only=readable_only,
            commit=False,
        )
        await self.session.commit()

        all_editions = (
            await self.books.readable_editions(book.id, owner_user_id)
            if readable_only
            else await self.books.editions(book.id)
        )
        progress_map = await self.reader.progress_for_editions(
            viewer_user_id,
            [item.id for item in all_editions],
        )
        available: list[ReaderEditionRecord] = []
        for item in all_editions:
            record = await self.library.get_current_edition_file_for_owner(owner_user_id, item.id)
            if record is None or record.stored_file.file_format not in {
                FileFormat.EPUB,
                FileFormat.TXT,
            }:
                continue
            if record.stored_file.file_format is FileFormat.TXT and record.normalized_file is None:
                continue
            available.append(ReaderEditionRecord(item, record, progress_map.get(item.id)))
        return OpenedReader(
            book=book,
            edition=edition,
            file=file_record,
            publication=publication,
            progress=progress,
            settings=reader_settings,
            editions=tuple(available),
        )

    async def section(
        self,
        *,
        owner_user_id: UUID,
        edition_id: UUID,
        section_id: str,
        readable_only: bool,
    ) -> ReaderSectionContent:
        _, file_record = await self._readable_edition(
            owner_user_id, edition_id, readable_only=readable_only
        )
        publication = await self._publication(file_record)
        source_file = self._content_file(file_record)

        def load() -> ReaderSectionContent:
            try:
                with self.storage.open_file(source_file.storage_key) as source:
                    if publication.file_format is FileFormat.EPUB:
                        return read_epub_section(source, publication, section_id)
                    return read_text_section(source, publication, section_id)
            except StorageError as exc:
                raise ApplicationError(
                    "reader_file_unavailable",
                    "阅读文件缺失或无法访问。",
                    status_code=500,
                ) from exc

        return await to_thread.run_sync(load)

    async def resource(
        self,
        *,
        owner_user_id: UUID,
        edition_id: UUID,
        resource_id: str,
        readable_only: bool,
    ) -> ReaderResourceContent:
        _, file_record = await self._readable_edition(
            owner_user_id, edition_id, readable_only=readable_only
        )
        if file_record.stored_file.file_format is not FileFormat.EPUB:
            raise ApplicationError("reader_resource_not_found", "书内资源不存在。", status_code=404)
        publication = await self._publication(file_record)

        def load() -> ReaderResourceContent:
            try:
                with self.storage.open_file(file_record.stored_file.storage_key) as source:
                    return read_epub_resource(
                        source,
                        publication,
                        resource_id,
                        max_bytes=self.settings.max_cover_bytes,
                        max_pixels=self.settings.max_cover_pixels,
                    )
            except StorageError as exc:
                raise ApplicationError(
                    "reader_file_unavailable",
                    "阅读文件缺失或无法访问。",
                    status_code=500,
                ) from exc

        return await to_thread.run_sync(load)

    async def save_progress(
        self,
        *,
        owner_user_id: UUID,
        viewer_user_id: UUID,
        device_id: UUID,
        edition_id: UUID,
        expected_version: int,
        section_id: str,
        block_id: str | None,
        section_progress: float,
        overall_progress: float,
        edition_file_revision: int,
        status: ReadingStatus | None,
        readable_only: bool,
    ) -> ReadingProgressModel:
        edition, file_record = await self._readable_edition(
            owner_user_id, edition_id, readable_only=readable_only
        )
        publication = await self._publication(file_record)
        if edition_file_revision != file_record.edition_file.revision:
            raise ApplicationError(
                "reader_file_changed",
                "Edition 文件已更新，请重新打开阅读器后再保存位置。",
                status_code=409,
                details={"current_file_revision": file_record.edition_file.revision},
            )
        if not any(section.id == section_id for section in publication.sections):
            raise ApplicationError("reader_section_not_found", "阅读章节不存在。", status_code=404)
        progress = await self.reader.get_progress(viewer_user_id, edition.id, for_update=True)
        if progress is None:
            if expected_version != 0:
                raise self._progress_conflict(None)
            is_last = publication.sections[-1].id == section_id
            inserted = await self.reader.create_progress_if_missing(
                user_id=viewer_user_id,
                edition_id=edition.id,
                status=(
                    status
                    or (
                        ReadingStatus.FINISHED
                        if is_last and overall_progress >= 0.995
                        else ReadingStatus.READING
                    )
                ),
                section_id=section_id,
                block_id=block_id,
                section_progress=section_progress,
                overall_progress=overall_progress,
                edition_file_revision=edition_file_revision,
                updated_device_id=device_id,
                at=datetime.now(UTC),
            )
            progress = await self.reader.get_progress(viewer_user_id, edition.id, for_update=True)
            if progress is None:
                raise RuntimeError("reading progress upsert did not produce a row")
            if not inserted:
                raise self._progress_conflict(progress)
            await self.session.commit()
            return progress
        elif progress.version != expected_version:
            raise self._progress_conflict(progress)
        now = datetime.now(UTC)
        progress.section_id = section_id
        progress.block_id = block_id
        progress.section_progress = section_progress
        progress.overall_progress = overall_progress
        progress.edition_file_revision = edition_file_revision
        if status is not None:
            progress.status = status
        elif progress.status is not ReadingStatus.FINISHED:
            is_last = publication.sections[-1].id == section_id
            progress.status = (
                ReadingStatus.FINISHED
                if is_last and overall_progress >= 0.995
                else ReadingStatus.READING
            )
        if progress.version == expected_version:
            progress.version += 1
        progress.updated_device_id = device_id
        progress.last_read_at = now
        progress.updated_at = now
        await self.session.commit()
        return progress

    async def get_settings(self, owner_user_id: UUID) -> ReaderSettingsModel:
        settings = await self._settings(owner_user_id)
        await self.session.commit()
        return settings

    async def update_settings(
        self,
        owner_user_id: UUID,
        changes: dict[str, object],
    ) -> ReaderSettingsModel:
        settings = await self._settings(owner_user_id)
        for field, value in changes.items():
            setattr(settings, field, value)
        settings.updated_at = datetime.now(UTC)
        await self.session.commit()
        return settings

    async def recent(
        self,
        viewer_user_id: UUID,
        owner_user_id: UUID,
        *,
        limit: int,
        readable_only: bool,
    ) -> list[RecentReadingRecord]:
        return await self.reader.recent(
            viewer_user_id,
            owner_user_id,
            limit=limit,
            readable_only=readable_only,
        )

    async def _settings(self, owner_user_id: UUID) -> ReaderSettingsModel:
        settings = await self.reader.get_settings(owner_user_id)
        if settings is None:
            settings = await self.reader.ensure_settings(owner_user_id, at=datetime.now(UTC))
        return settings

    async def _readable_edition(
        self,
        owner_user_id: UUID,
        edition_id: UUID,
        *,
        readable_only: bool,
    ) -> tuple[BookEditionModel, EditionFileRecord]:
        edition = (
            await self.editions.get_readable(owner_user_id, edition_id)
            if readable_only
            else await self.editions.get_for_owner(owner_user_id, edition_id)
        )
        if edition is None:
            raise ApplicationError("edition_not_found", "Edition 不存在。", status_code=404)
        record = await self.library.get_current_edition_file_for_owner(owner_user_id, edition.id)
        if record is None:
            raise ApplicationError(
                "reader_file_missing",
                "此 Edition 尚未关联可阅读文件。",
                status_code=422,
            )
        if record.stored_file.file_format not in {FileFormat.EPUB, FileFormat.TXT}:
            raise ApplicationError(
                "reader_format_unsupported",
                "v0.4.0 仅支持阅读 EPUB 和 TXT。",
                status_code=422,
            )
        if record.stored_file.file_format is FileFormat.TXT and record.normalized_file is None:
            raise ApplicationError(
                "reader_text_unavailable",
                "TXT 缺少上传阶段生成的规范化文本。",
                status_code=422,
            )
        return edition, record

    async def _publication(self, record: EditionFileRecord) -> ReaderPublication:
        source_file = self._content_file(record)

        def build() -> ReaderPublication:
            try:
                with self.storage.open_file(source_file.storage_key) as source:
                    if record.stored_file.file_format is FileFormat.EPUB:
                        return build_epub_publication(
                            source,
                            file_revision=record.edition_file.revision,
                        )
                    return build_text_publication(
                        source,
                        file_revision=record.edition_file.revision,
                    )
            except StorageError as exc:
                raise ApplicationError(
                    "reader_file_unavailable",
                    "阅读文件缺失或无法访问。",
                    status_code=500,
                ) from exc

        return await to_thread.run_sync(build)

    @staticmethod
    def _content_file(record: EditionFileRecord):  # type: ignore[no-untyped-def]
        if record.stored_file.file_format is FileFormat.TXT:
            if record.normalized_file is None:
                raise ApplicationError(
                    "reader_text_unavailable",
                    "TXT 缺少上传阶段生成的规范化文本。",
                    status_code=422,
                )
            return record.normalized_file
        return record.stored_file

    @staticmethod
    def _progress_conflict(progress: ReadingProgressModel | None) -> ApplicationError:
        details: dict[str, object] = {"current_version": progress.version if progress else 0}
        if progress is not None:
            details.update(
                {
                    "section_id": progress.section_id,
                    "block_id": progress.block_id,
                    "section_progress": progress.section_progress,
                    "overall_progress": progress.overall_progress,
                    "status": progress.status.value,
                    "edition_file_revision": progress.edition_file_revision,
                    "last_read_at": progress.last_read_at.isoformat(),
                }
            )
        return ApplicationError(
            "reading_progress_conflict",
            "另一台设备或标签页已更新阅读位置。已保留较新的服务端位置。",
            status_code=409,
            details=details,
        )
