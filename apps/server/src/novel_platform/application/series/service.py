from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from novel_platform.application.errors import ApplicationError
from novel_platform.infrastructure.database.models import (
    BookModel,
    BookSeriesModel,
    SeriesMembershipModel,
)
from novel_platform.infrastructure.repositories.books import BookRepository
from novel_platform.infrastructure.repositories.series import SeriesBookRecord, SeriesRepository


class SeriesService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.series = SeriesRepository(session)
        self.books = BookRepository(session)

    async def create(
        self,
        owner_user_id: UUID,
        *,
        name: str,
        description: str | None,
    ) -> BookSeriesModel:
        series = await self.series.add(
            BookSeriesModel(
                id=uuid4(),
                owner_user_id=owner_user_id,
                name=self._name(name),
                description=self._optional_text(description),
            )
        )
        await self.session.commit()
        return series

    async def list_all(self, owner_user_id: UUID) -> list[tuple[BookSeriesModel, int]]:
        return await self.series.list_for_owner(owner_user_id)

    async def list_readable(self, owner_user_id: UUID) -> list[tuple[BookSeriesModel, int]]:
        return await self.series.list_readable(owner_user_id)

    async def detail(
        self,
        owner_user_id: UUID,
        series_id: UUID,
    ) -> tuple[BookSeriesModel, list[SeriesBookRecord]]:
        series = await self._get(series_id, owner_user_id)
        return series, await self.series.books(series.id)

    async def readable_detail(
        self,
        owner_user_id: UUID,
        series_id: UUID,
    ) -> tuple[BookSeriesModel, list[SeriesBookRecord]]:
        series = await self._get(series_id, owner_user_id)
        records = await self.series.readable_books(series.id, owner_user_id)
        if not records:
            raise ApplicationError("series_not_found", "系列不存在。", status_code=404)
        return series, records

    async def update(
        self,
        owner_user_id: UUID,
        series_id: UUID,
        changes: dict[str, object],
    ) -> BookSeriesModel:
        series = await self._get(series_id, owner_user_id, for_update=True)
        if "name" in changes:
            series.name = self._name(str(changes["name"]))
        if "description" in changes:
            value = changes["description"]
            series.description = self._optional_text(value if isinstance(value, str) else None)
        series.updated_at = datetime.now(UTC)
        await self.session.commit()
        return series

    async def delete(self, owner_user_id: UUID, series_id: UUID) -> None:
        series = await self._get(series_id, owner_user_id, for_update=True)
        await self.session.delete(series)
        await self.session.commit()

    async def add_book(
        self,
        owner_user_id: UUID,
        series_id: UUID,
        book_id: UUID,
        *,
        commit: bool = True,
    ) -> SeriesMembershipModel:
        series = await self._get(series_id, owner_user_id, for_update=True)
        book = await self.books.get(book_id, owner_user_id)
        if book is None:
            raise ApplicationError("book_not_found", "Book 不存在。", status_code=404)
        membership = await self.series.membership_for_book(book.id)
        if membership is not None:
            if membership.series_id == series.id:
                return membership
            raise ApplicationError(
                "book_already_in_series",
                "该 Book 已属于另一个系列，请先将它移出原系列。",
                status_code=409,
            )
        membership = SeriesMembershipModel(
            series_id=series.id,
            book_id=book.id,
            position=await self.series.next_position(series.id),
        )
        self.session.add(membership)
        series.updated_at = datetime.now(UTC)
        await self.session.flush()
        if commit:
            await self.session.commit()
        return membership

    async def add_new_book(
        self,
        owner_user_id: UUID,
        series_id: UUID,
        book: BookModel,
    ) -> SeriesMembershipModel:
        if book.owner_user_id != owner_user_id:
            raise ApplicationError("book_not_found", "Book 不存在。", status_code=404)
        return await self.add_book(owner_user_id, series_id, book.id, commit=False)

    async def remove_book(
        self,
        owner_user_id: UUID,
        series_id: UUID,
        book_id: UUID,
    ) -> None:
        series = await self._get(series_id, owner_user_id, for_update=True)
        book = await self.books.get(book_id, owner_user_id)
        if book is None:
            raise ApplicationError("book_not_found", "Book 不存在。", status_code=404)
        membership = await self.series.membership_for_book(book.id)
        if membership is None or membership.series_id != series.id:
            raise ApplicationError(
                "series_membership_not_found",
                "该 Book 不在此系列中。",
                status_code=404,
            )
        await self.session.delete(membership)
        series.updated_at = datetime.now(UTC)
        await self.session.commit()

    async def _get(
        self,
        series_id: UUID,
        owner_user_id: UUID,
        *,
        for_update: bool = False,
    ) -> BookSeriesModel:
        series = await self.series.get(series_id, owner_user_id, for_update=for_update)
        if series is None:
            raise ApplicationError("series_not_found", "系列不存在。", status_code=404)
        return series

    @staticmethod
    def _name(value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ApplicationError("invalid_series_name", "系列名称不能为空。", status_code=422)
        return normalized

    @staticmethod
    def _optional_text(value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None
