from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from novel_platform.domain.editions.models import EditionStatus
from novel_platform.infrastructure.database.models import (
    BookEditionModel,
    BookModel,
    BookSeriesModel,
    EditionFileModel,
    SeriesMembershipModel,
    StoredFileModel,
)


@dataclass(frozen=True, slots=True)
class SeriesBookRecord:
    membership: SeriesMembershipModel
    book: BookModel
    edition_count: int


class SeriesRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add(self, series: BookSeriesModel) -> BookSeriesModel:
        self.session.add(series)
        await self.session.flush()
        await self.session.refresh(series)
        return series

    async def get(
        self,
        series_id: UUID,
        owner_user_id: UUID,
        *,
        for_update: bool = False,
    ) -> BookSeriesModel | None:
        statement = select(BookSeriesModel).where(
            BookSeriesModel.id == series_id,
            BookSeriesModel.owner_user_id == owner_user_id,
        )
        if for_update:
            statement = statement.with_for_update()
        return (await self.session.scalars(statement)).one_or_none()

    async def list_for_owner(
        self,
        owner_user_id: UUID,
    ) -> list[tuple[BookSeriesModel, int]]:
        statement = (
            select(BookSeriesModel, func.count(SeriesMembershipModel.book_id))
            .outerjoin(
                SeriesMembershipModel,
                SeriesMembershipModel.series_id == BookSeriesModel.id,
            )
            .where(BookSeriesModel.owner_user_id == owner_user_id)
            .group_by(BookSeriesModel.id)
            .order_by(BookSeriesModel.updated_at.desc(), BookSeriesModel.id.asc())
        )
        return [
            (series, int(book_count))
            for series, book_count in (await self.session.execute(statement)).all()
        ]

    async def list_readable(
        self,
        owner_user_id: UUID,
    ) -> list[tuple[BookSeriesModel, int]]:
        statement = (
            select(
                BookSeriesModel,
                func.count(func.distinct(SeriesMembershipModel.book_id)),
            )
            .join(
                SeriesMembershipModel,
                SeriesMembershipModel.series_id == BookSeriesModel.id,
            )
            .join(BookModel, BookModel.id == SeriesMembershipModel.book_id)
            .join(BookEditionModel, BookEditionModel.book_id == BookModel.id)
            .join(
                EditionFileModel,
                (EditionFileModel.edition_id == BookEditionModel.id)
                & EditionFileModel.is_current.is_(True),
            )
            .join(StoredFileModel, StoredFileModel.id == EditionFileModel.stored_file_id)
            .where(
                BookSeriesModel.owner_user_id == owner_user_id,
                BookModel.owner_user_id == owner_user_id,
                BookEditionModel.status == EditionStatus.READY,
                StoredFileModel.owner_user_id == owner_user_id,
            )
            .group_by(BookSeriesModel.id)
            .order_by(BookSeriesModel.updated_at.desc(), BookSeriesModel.id.asc())
        )
        return [
            (series, int(book_count))
            for series, book_count in (await self.session.execute(statement)).all()
        ]

    async def books(self, series_id: UUID) -> list[SeriesBookRecord]:
        statement = (
            select(
                SeriesMembershipModel,
                BookModel,
                func.count(BookEditionModel.id).label("edition_count"),
            )
            .join(BookModel, BookModel.id == SeriesMembershipModel.book_id)
            .outerjoin(BookEditionModel, BookEditionModel.book_id == BookModel.id)
            .where(SeriesMembershipModel.series_id == series_id)
            .group_by(SeriesMembershipModel.book_id, BookModel.id)
            .order_by(SeriesMembershipModel.position.asc(), SeriesMembershipModel.book_id.asc())
        )
        return [
            SeriesBookRecord(membership, book, int(edition_count))
            for membership, book, edition_count in (await self.session.execute(statement)).all()
        ]

    async def readable_books(self, series_id: UUID, owner_user_id: UUID) -> list[SeriesBookRecord]:
        statement = (
            select(
                SeriesMembershipModel,
                BookModel,
                func.count(func.distinct(BookEditionModel.id)).label("edition_count"),
            )
            .join(BookModel, BookModel.id == SeriesMembershipModel.book_id)
            .join(BookEditionModel, BookEditionModel.book_id == BookModel.id)
            .join(
                EditionFileModel,
                (EditionFileModel.edition_id == BookEditionModel.id)
                & EditionFileModel.is_current.is_(True),
            )
            .join(StoredFileModel, StoredFileModel.id == EditionFileModel.stored_file_id)
            .where(
                SeriesMembershipModel.series_id == series_id,
                BookModel.owner_user_id == owner_user_id,
                BookEditionModel.status == EditionStatus.READY,
                StoredFileModel.owner_user_id == owner_user_id,
            )
            .group_by(SeriesMembershipModel.book_id, BookModel.id)
            .order_by(SeriesMembershipModel.position.asc(), SeriesMembershipModel.book_id.asc())
        )
        return [
            SeriesBookRecord(membership, book, int(edition_count))
            for membership, book, edition_count in (await self.session.execute(statement)).all()
        ]

    async def membership_for_book(self, book_id: UUID) -> SeriesMembershipModel | None:
        return await self.session.get(SeriesMembershipModel, book_id)

    async def next_position(self, series_id: UUID) -> int:
        statement = select(func.coalesce(func.max(SeriesMembershipModel.position), 0) + 1).where(
            SeriesMembershipModel.series_id == series_id
        )
        return int((await self.session.scalar(statement)) or 1)

    async def membership_summaries(
        self,
        owner_user_id: UUID,
        book_ids: list[UUID],
    ) -> dict[UUID, tuple[UUID, str]]:
        if not book_ids:
            return {}
        statement = (
            select(
                SeriesMembershipModel.book_id,
                BookSeriesModel.id,
                BookSeriesModel.name,
            )
            .join(BookSeriesModel, BookSeriesModel.id == SeriesMembershipModel.series_id)
            .where(
                BookSeriesModel.owner_user_id == owner_user_id,
                SeriesMembershipModel.book_id.in_(book_ids),
            )
        )
        return {
            book_id: (series_id, name)
            for book_id, series_id, name in await self.session.execute(statement)
        }
