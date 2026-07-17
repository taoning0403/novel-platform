from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from novel_platform.infrastructure.database.models import UserBookPreferenceModel


class PreferenceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, user_id: UUID, book_id: UUID) -> UserBookPreferenceModel | None:
        statement = select(UserBookPreferenceModel).where(
            UserBookPreferenceModel.user_id == user_id,
            UserBookPreferenceModel.book_id == book_id,
        )
        return (await self.session.scalars(statement)).one_or_none()

    async def add(self, preference: UserBookPreferenceModel) -> UserBookPreferenceModel:
        self.session.add(preference)
        await self.session.flush()
        await self.session.refresh(preference)
        return preference

    async def ensure(self, preference: UserBookPreferenceModel) -> UserBookPreferenceModel:
        statement = (
            insert(UserBookPreferenceModel)
            .values(
                user_id=preference.user_id,
                book_id=preference.book_id,
                preferred_edition_id=None,
                last_opened_edition_id=None,
                created_at=preference.created_at,
                updated_at=preference.updated_at,
            )
            .on_conflict_do_nothing(
                index_elements=[
                    UserBookPreferenceModel.user_id,
                    UserBookPreferenceModel.book_id,
                ]
            )
        )
        await self.session.execute(statement)
        existing = await self.get(preference.user_id, preference.book_id)
        if existing is None:
            raise RuntimeError("preference upsert did not produce a row")
        return existing
