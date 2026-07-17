from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import and_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from novel_platform.domain.editions.models import EditionStatus
from novel_platform.domain.library.models import FileFormat
from novel_platform.domain.reader.models import ReaderFontFamily, ReaderTheme, ReadingStatus
from novel_platform.infrastructure.database.models import (
    BookEditionModel,
    BookModel,
    BookSeriesModel,
    EditionFileModel,
    ReaderSettingsModel,
    ReadingProgressModel,
    SeriesMembershipModel,
    StoredFileModel,
)


@dataclass(frozen=True, slots=True)
class RecentReadingRecord:
    progress: ReadingProgressModel
    edition: BookEditionModel
    book: BookModel
    file_format: FileFormat
    series_id: UUID | None
    series_name: str | None


class ReaderRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_progress(
        self,
        user_id: UUID,
        edition_id: UUID,
        *,
        for_update: bool = False,
    ) -> ReadingProgressModel | None:
        statement = select(ReadingProgressModel).where(
            ReadingProgressModel.user_id == user_id,
            ReadingProgressModel.edition_id == edition_id,
        )
        if for_update:
            statement = statement.with_for_update()
        return (await self.session.scalars(statement)).one_or_none()

    async def create_progress_if_missing(
        self,
        *,
        user_id: UUID,
        edition_id: UUID,
        status: ReadingStatus,
        section_id: str,
        block_id: str | None,
        section_progress: float,
        overall_progress: float,
        edition_file_revision: int,
        updated_device_id: UUID,
        at: datetime,
    ) -> bool:
        statement = (
            insert(ReadingProgressModel)
            .values(
                user_id=user_id,
                edition_id=edition_id,
                status=status,
                section_id=section_id,
                block_id=block_id,
                section_progress=section_progress,
                overall_progress=overall_progress,
                edition_file_revision=edition_file_revision,
                version=1,
                updated_device_id=updated_device_id,
                last_read_at=at,
                created_at=at,
                updated_at=at,
            )
            .on_conflict_do_nothing(
                index_elements=[
                    ReadingProgressModel.user_id,
                    ReadingProgressModel.edition_id,
                ]
            )
            .returning(ReadingProgressModel.edition_id)
        )
        return (await self.session.scalar(statement)) is not None

    async def progress_for_editions(
        self,
        user_id: UUID,
        edition_ids: list[UUID],
    ) -> dict[UUID, ReadingProgressModel]:
        if not edition_ids:
            return {}
        statement = select(ReadingProgressModel).where(
            ReadingProgressModel.user_id == user_id,
            ReadingProgressModel.edition_id.in_(edition_ids),
        )
        return {
            progress.edition_id: progress
            for progress in (await self.session.scalars(statement)).all()
        }

    async def get_settings(self, user_id: UUID) -> ReaderSettingsModel | None:
        return await self.session.get(ReaderSettingsModel, user_id)

    async def ensure_settings(self, user_id: UUID, *, at: datetime) -> ReaderSettingsModel:
        statement = (
            insert(ReaderSettingsModel)
            .values(
                user_id=user_id,
                font_size=18,
                line_height=1.8,
                content_width=760,
                font_family=ReaderFontFamily.SERIF,
                theme=ReaderTheme.LIGHT,
                created_at=at,
                updated_at=at,
            )
            .on_conflict_do_nothing(index_elements=[ReaderSettingsModel.user_id])
        )
        await self.session.execute(statement)
        settings = await self.get_settings(user_id)
        if settings is None:
            raise RuntimeError("reader settings upsert did not produce a row")
        return settings

    async def recent(
        self,
        user_id: UUID,
        owner_user_id: UUID,
        *,
        limit: int,
        readable_only: bool,
    ) -> list[RecentReadingRecord]:
        statement = (
            select(
                ReadingProgressModel,
                BookEditionModel,
                BookModel,
                StoredFileModel.file_format,
                BookSeriesModel.id,
                BookSeriesModel.name,
            )
            .join(BookEditionModel, BookEditionModel.id == ReadingProgressModel.edition_id)
            .join(BookModel, BookModel.id == BookEditionModel.book_id)
            .join(
                EditionFileModel,
                and_(
                    EditionFileModel.edition_id == BookEditionModel.id,
                    EditionFileModel.is_current.is_(True),
                ),
            )
            .join(StoredFileModel, StoredFileModel.id == EditionFileModel.stored_file_id)
            .outerjoin(SeriesMembershipModel, SeriesMembershipModel.book_id == BookModel.id)
            .outerjoin(BookSeriesModel, BookSeriesModel.id == SeriesMembershipModel.series_id)
            .where(
                ReadingProgressModel.user_id == user_id,
                BookModel.owner_user_id == owner_user_id,
                StoredFileModel.owner_user_id == owner_user_id,
            )
            .order_by(ReadingProgressModel.last_read_at.desc(), ReadingProgressModel.edition_id)
            .limit(limit)
        )
        if readable_only:
            statement = statement.where(BookEditionModel.status == EditionStatus.READY)
        return [
            RecentReadingRecord(
                progress=progress,
                edition=edition,
                book=book,
                file_format=file_format,
                series_id=series_id,
                series_name=series_name,
            )
            for progress, edition, book, file_format, series_id, series_name in (
                await self.session.execute(statement)
            ).all()
        ]
