from typing import Annotated

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from novel_platform.api.dependencies.database import DatabaseSession
from novel_platform.application.auth.context import AuthContext
from novel_platform.application.auth.security import TokenService
from novel_platform.application.auth.service import AuthService
from novel_platform.application.errors import ApplicationError
from novel_platform.config import get_settings
from novel_platform.domain.auth.models import UserRole
from novel_platform.infrastructure.database.models import AuthSessionModel, DeviceModel, UserModel

bearer_scheme = HTTPBearer(auto_error=False, scheme_name="BearerAuth")
BearerCredentials = Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)]


def authentication_required() -> ApplicationError:
    return ApplicationError(
        "authentication_required",
        "需要登录后才能访问。",
        status_code=401,
        headers={"WWW-Authenticate": "Bearer"},
    )


async def _active_context(
    session: DatabaseSession,
    credentials: BearerCredentials,
    *,
    allow_recovery: bool,
) -> AuthContext:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise authentication_required()
    claims = TokenService(get_settings()).decode_access_token(credentials.credentials)
    auth_session = await session.get(AuthSessionModel, claims.session_id)
    if (
        auth_session is None
        or auth_session.user_id != claims.user_id
        or auth_session.device_id != claims.device_id
    ):
        raise AuthService.invalid_session()
    context = await AuthService(session, get_settings()).active_context(auth_session)
    if context.session.recovery_mode and not allow_recovery:
        raise ApplicationError(
            "recovery_session_restricted",
            "恢复会话只能用于注册或重设管理员 Passkey。",
            status_code=403,
        )
    return context


async def get_current_auth(
    session: DatabaseSession,
    credentials: BearerCredentials,
) -> AuthContext:
    return await _active_context(session, credentials, allow_recovery=False)


async def get_recovery_or_current_auth(
    session: DatabaseSession,
    credentials: BearerCredentials,
) -> AuthContext:
    return await _active_context(session, credentials, allow_recovery=True)


async def get_logout_auth(
    session: DatabaseSession,
    credentials: BearerCredentials,
) -> AuthContext:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise authentication_required()
    claims = TokenService(get_settings()).decode_access_token(credentials.credentials)
    user = await session.get(UserModel, claims.user_id)
    auth_session = await session.get(AuthSessionModel, claims.session_id)
    device = await session.get(DeviceModel, claims.device_id)
    if user is None or auth_session is None or device is None:
        raise authentication_required()
    if auth_session.user_id != user.id or auth_session.device_id != device.id:
        raise authentication_required()
    return AuthContext(
        user=user,
        device=device,
        session=auth_session,
        capabilities=frozenset(),
    )


async def get_current_admin(
    context: Annotated[AuthContext, Depends(get_current_auth)],
) -> AuthContext:
    if context.user.role != UserRole.ADMIN:
        raise ApplicationError("admin_required", "需要管理员权限。", status_code=403)
    return context


async def get_passkey_admin(
    context: Annotated[AuthContext, Depends(get_recovery_or_current_auth)],
) -> AuthContext:
    if context.user.role != UserRole.ADMIN:
        raise ApplicationError("admin_required", "需要管理员权限。", status_code=403)
    return context


CurrentAuth = Annotated[AuthContext, Depends(get_current_auth)]
LogoutAuth = Annotated[AuthContext, Depends(get_logout_auth)]
CurrentAdmin = Annotated[AuthContext, Depends(get_current_admin)]
PasskeyAdmin = Annotated[AuthContext, Depends(get_passkey_admin)]
