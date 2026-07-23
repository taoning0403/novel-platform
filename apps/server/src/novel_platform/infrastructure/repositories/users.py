from uuid import UUID

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from novel_platform.domain.auth.models import UserRole, UserStatus
from novel_platform.infrastructure.database.models import UserModel


class UserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add(self, user: UserModel) -> UserModel:
        self.session.add(user)
        await self.session.flush()
        await self.session.refresh(user)
        return user

    async def get(self, user_id: UUID) -> UserModel | None:
        return await self.session.get(UserModel, user_id)

    async def get_visible(self, user_id: UUID) -> UserModel | None:
        statement = select(UserModel).where(
            UserModel.id == user_id,
            UserModel.status != UserStatus.PENDING_SETUP,
        )
        return (await self.session.scalars(statement)).one_or_none()

    async def display_names(self, user_ids: set[UUID]) -> dict[UUID, str]:
        if not user_ids:
            return {}
        statement = select(UserModel.id, UserModel.display_name).where(
            UserModel.id.in_(user_ids),
            UserModel.status != UserStatus.PENDING_SETUP,
        )
        return {
            user_id: display_name for user_id, display_name in await self.session.execute(statement)
        }

    async def get_by_normalized_username(self, normalized_username: str) -> UserModel | None:
        statement = select(UserModel).where(UserModel.normalized_username == normalized_username)
        return (await self.session.scalars(statement)).one_or_none()

    async def pending_setup_for_update(self) -> UserModel | None:
        statement = (
            select(UserModel).where(UserModel.status == UserStatus.PENDING_SETUP).with_for_update()
        )
        return (await self.session.scalars(statement)).one_or_none()

    async def setup_required(self) -> bool:
        statement = (
            select(UserModel.id).where(UserModel.status == UserStatus.PENDING_SETUP).limit(1)
        )
        return (await self.session.scalar(statement)) is not None

    async def list_page(
        self,
        *,
        limit: int,
        offset: int,
        status: UserStatus | None,
        role: UserRole | None,
    ) -> list[UserModel]:
        statement: Select[tuple[UserModel]] = select(UserModel).where(
            UserModel.status != UserStatus.PENDING_SETUP
        )
        if status is not None:
            statement = statement.where(UserModel.status == status)
        if role is not None:
            statement = statement.where(UserModel.role == role)
        statement = (
            statement.order_by(UserModel.created_at.asc(), UserModel.id.asc())
            .limit(limit)
            .offset(offset)
        )
        return list((await self.session.scalars(statement)).all())

    async def active_admins_for_update(self) -> list[UserModel]:
        statement = (
            select(UserModel)
            .where(UserModel.role == UserRole.ADMIN, UserModel.status == UserStatus.ACTIVE)
            .order_by(UserModel.id)
            .with_for_update()
        )
        return list((await self.session.scalars(statement)).all())
