from dataclasses import dataclass
from http import HTTPStatus
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from novel_platform.application.auth.context import AuthContext
from novel_platform.application.errors import ApplicationError
from novel_platform.domain.auth.capabilities import CredentialCapability
from novel_platform.domain.auth.models import UserRole
from novel_platform.infrastructure.repositories.site import SiteRepository


@dataclass(frozen=True, slots=True)
class LibraryAccessScope:
    viewer_user_id: UUID
    owner_user_id: UUID
    can_manage: bool
    capabilities: frozenset[CredentialCapability]

    def has(self, capability: CredentialCapability) -> bool:
        return self.can_manage or capability in self.capabilities


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
        return LibraryAccessScope(
            viewer_user_id=context.user.id,
            owner_user_id=owner_user_id,
            can_manage=can_manage,
            capabilities=context.capabilities,
        )

    async def require_manager(self, context: AuthContext) -> UUID:
        scope = await self.scope(context)
        if not scope.can_manage:
            raise ApplicationError(
                "library_management_forbidden",
                "受邀阅读者不能修改站点藏书。",
                status_code=HTTPStatus.FORBIDDEN,
            )
        return scope.owner_user_id

    async def require_capability(
        self,
        context: AuthContext,
        capability: CredentialCapability,
    ) -> LibraryAccessScope:
        scope = await self.scope(context)
        if not scope.has(capability):
            raise ApplicationError(
                "library_capability_required",
                "当前访问凭证不包含所需能力。",
                status_code=HTTPStatus.FORBIDDEN,
                details={"capability": capability.value},
            )
        return scope

    async def require_upload(self, context: AuthContext) -> LibraryAccessScope:
        return await self.require_capability(context, CredentialCapability.LIBRARY_UPLOAD)

    async def require_translation(self, context: AuthContext) -> LibraryAccessScope:
        return await self.require_capability(context, CredentialCapability.TRANSLATION_USE)

    async def require_any_capability(
        self,
        context: AuthContext,
        *capabilities: CredentialCapability,
    ) -> LibraryAccessScope:
        scope = await self.scope(context)
        if not any(scope.has(capability) for capability in capabilities):
            raise ApplicationError(
                "library_capability_required",
                "当前访问凭证不包含所需能力。",
                status_code=HTTPStatus.FORBIDDEN,
                details={"capabilities": [item.value for item in capabilities]},
            )
        return scope
