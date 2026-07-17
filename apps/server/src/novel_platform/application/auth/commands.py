from dataclasses import dataclass
from typing import Any
from uuid import UUID

from novel_platform.domain.auth.models import DevicePlatform


@dataclass(frozen=True, slots=True)
class LoginDevice:
    client_instance_id: UUID
    name: str
    platform: DevicePlatform
    app_version: str | None


@dataclass(frozen=True, slots=True)
class CredentialLogin:
    credential: str
    device: LoginDevice
    client_ip: str
    user_agent: str | None
    device_secret: str | None


@dataclass(frozen=True, slots=True)
class PasskeyLogin:
    challenge_id: UUID
    credential: dict[str, Any]
    device: LoginDevice
    client_ip: str
    user_agent: str | None
    device_secret: str | None
