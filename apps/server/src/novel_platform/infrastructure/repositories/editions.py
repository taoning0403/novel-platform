from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from novel_platform.domain.editions.models import CreationMethod, EditionStatus
from novel_platform.infrastructure.database.models import (
    BookEditionModel,
    BookModel,
    EditionFileModel,
    StoredFileModel,
)


class EditionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add(self, edition: BookEditionModel) -> BookEditionModel:
        self.session.add(edition)
        await self.session.flush()
        await self.session.refresh(edition)
        return edition

    async def get(self, edition_id: UUID) -> BookEditionModel | None:
        return await self.session.get(BookEditionModel, edition_id)

    async def get_for_book(
        self,
        book_id: UUID,
        edition_id: UUID,
        *,
        for_update: bool = False,
    ) -> BookEditionModel | None:
        statement = select(BookEditionModel).where(
            BookEditionModel.id == edition_id,
            BookEditionModel.book_id == book_id,
        )
        if for_update:
            statement = statement.with_for_update()
        result = await self.session.execute(statement)
        return result.scalar_one_or_none()

    async def get_for_owner(self, owner_user_id: UUID, edition_id: UUID) -> BookEditionModel | None:
        statement = (
            select(BookEditionModel)
            .join(BookModel, BookModel.id == BookEditionModel.book_id)
            .where(
                BookEditionModel.id == edition_id,
                BookModel.owner_user_id == owner_user_id,
            )
        )
        return (await self.session.scalars(statement)).one_or_none()

    async def get_readable(self, owner_user_id: UUID, edition_id: UUID) -> BookEditionModel | None:
        statement = (
            select(BookEditionModel)
            .join(BookModel, BookModel.id == BookEditionModel.book_id)
            .join(EditionFileModel, EditionFileModel.edition_id == BookEditionModel.id)
            .join(StoredFileModel, StoredFileModel.id == EditionFileModel.stored_file_id)
            .where(
                BookEditionModel.id == edition_id,
                BookEditionModel.status == EditionStatus.READY,
                EditionFileModel.is_current.is_(True),
                BookModel.owner_user_id == owner_user_id,
                StoredFileModel.owner_user_id == owner_user_id,
            )
        )
        return (await self.session.scalars(statement)).one_or_none()

    async def get_visible_for_reader(
        self,
        owner_user_id: UUID,
        viewer_user_id: UUID,
        edition_id: UUID,
    ) -> BookEditionModel | None:
        """Return a public-ready edition or the viewer's own generated draft."""
        statement = (
            select(BookEditionModel)
            .join(BookModel, BookModel.id == BookEditionModel.book_id)
            .join(EditionFileModel, EditionFileModel.edition_id == BookEditionModel.id)
            .join(StoredFileModel, StoredFileModel.id == EditionFileModel.stored_file_id)
            .where(
                BookEditionModel.id == edition_id,
                or_(
                    BookEditionModel.status == EditionStatus.READY,
                    and_(
                        BookEditionModel.status == EditionStatus.DRAFT,
                        BookEditionModel.creation_method == CreationMethod.GENERATED,
                        BookEditionModel.created_by_user_id == viewer_user_id,
                    ),
                ),
                EditionFileModel.is_current.is_(True),
                BookModel.owner_user_id == owner_user_id,
                StoredFileModel.owner_user_id == owner_user_id,
            )
        )
        return (await self.session.scalars(statement)).one_or_none()

    async def dependents(self, edition_id: UUID) -> list[BookEditionModel]:
        statement = select(BookEditionModel).where(
            (BookEditionModel.source_edition_id == edition_id)
            | (BookEditionModel.supersedes_edition_id == edition_id)
        )
        return list((await self.session.scalars(statement)).all())
