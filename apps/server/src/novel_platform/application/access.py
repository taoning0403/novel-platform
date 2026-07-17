from dataclasses import dataclass
from http import HTTPStatus
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from novel_platform.application.auth.context import AuthContext
from novel_platform.application.errors import ApplicationError
from novel_platform.domain.auth.models import UserRole
from novel_platform.infrastructure.repositories.site import SiteRepository


@dataclass(frozen=True, slots=True)
class LibraryAccessScope:
    viewer_user_id: UUID
    owner_user_id: UUID
    can_manage: bool


class LibraryAccessService:
    def __init__(self, session: AsyncSession) -> None:
        self.site = SiteRepository(session)

    async def scope(self, context: AuthContext) -> LibraryAccessScope:
        settings = await self.site.get()
        owner_user_id = settings.library_owner_user_id
        if owner_user_id is None or settings.migration_completed_at is None:
            raise ApplicationError(
                "library_not_initialized",
                "站点藏书尚未完成初始化。",
                status_code=HTTPStatus.SERVICE_UNAVAILABLE,
            )
        can_manage = context.user.role == UserRole.ADMIN and context.user.id == owner_user_id
        return LibraryAccessScope(context.user.id, owner_user_id, can_manage)

    async def require_manager(self, context: AuthContext) -> UUID:
        scope = await self.scope(context)
        if not scope.can_manage:
            raise ApplicationError(
                "library_management_forbidden",
                "受邀阅读者不能修改站点藏书。",
                status_code=HTTPStatus.FORBIDDEN,
            )
        return scope.owner_user_id
