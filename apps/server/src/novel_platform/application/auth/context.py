from dataclasses import dataclass

from novel_platform.infrastructure.database.models import AuthSessionModel, DeviceModel, UserModel


@dataclass(frozen=True, slots=True)
class AuthContext:
    user: UserModel
    device: DeviceModel
    session: AuthSessionModel


@dataclass(frozen=True, slots=True)
class TokenResult:
    access_token: str
    expires_in: int
    refresh_token: str
    device_secret: str | None
    context: AuthContext
