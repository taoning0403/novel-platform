from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from novel_platform.infrastructure.database.models import EditionTranslationRunModel


class TranslationRunRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add(self, run: EditionTranslationRunModel) -> EditionTranslationRunModel:
        self.session.add(run)
        await self.session.flush()
        await self.session.refresh(run)
        return run

    async def get(
        self,
        owner_user_id: UUID,
        run_id: UUID,
        *,
        creator_user_id: UUID | None = None,
        for_update: bool = False,
    ) -> EditionTranslationRunModel | None:
        statement = select(EditionTranslationRunModel).where(
            EditionTranslationRunModel.id == run_id,
            EditionTranslationRunModel.library_owner_user_id == owner_user_id,
        )
        if creator_user_id is not None:
            statement = statement.where(
                EditionTranslationRunModel.created_by_user_id == creator_user_id
            )
        if for_update:
            statement = statement.with_for_update()
        return (await self.session.scalars(statement)).one_or_none()

    async def get_by_client_request(
        self,
        owner_user_id: UUID,
        creator_user_id: UUID,
        client_request_id: UUID,
    ) -> EditionTranslationRunModel | None:
        statement = select(EditionTranslationRunModel).where(
            EditionTranslationRunModel.library_owner_user_id == owner_user_id,
            EditionTranslationRunModel.created_by_user_id == creator_user_id,
            EditionTranslationRunModel.client_request_id == client_request_id,
        )
        return (await self.session.scalars(statement)).one_or_none()

    async def list_visible(
        self,
        owner_user_id: UUID,
        *,
        creator_user_id: UUID | None = None,
        book_id: UUID | None = None,
    ) -> list[EditionTranslationRunModel]:
        statement = select(EditionTranslationRunModel).where(
            EditionTranslationRunModel.library_owner_user_id == owner_user_id
        )
        if creator_user_id is not None:
            statement = statement.where(
                EditionTranslationRunModel.created_by_user_id == creator_user_id
            )
        if book_id is not None:
            statement = statement.where(EditionTranslationRunModel.book_id == book_id)
        statement = statement.order_by(
            EditionTranslationRunModel.created_at.desc(),
            EditionTranslationRunModel.id.desc(),
        )
        return list((await self.session.scalars(statement)).all())
