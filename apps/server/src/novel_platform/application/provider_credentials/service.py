import base64
import binascii
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID, uuid4

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession

from novel_platform.application.auth.context import AuthContext
from novel_platform.application.errors import ApplicationError
from novel_platform.config import Settings
from novel_platform.infrastructure.database.models import ProviderCredentialVersionModel
from novel_platform.infrastructure.repositories.auth import AuthRepository
from novel_platform.infrastructure.repositories.provider_credentials import (
    PROVIDER_ID,
    ProviderCredentialRepository,
    UsageTotals,
)

ALGORITHM = "aes-256-gcm-v1"


class ProviderCredentialCipherSettings(Protocol):
    @property
    def provider_credential_master_key(self) -> SecretStr | None: ...


class ProviderCredentialConfigurationError(RuntimeError):
    pass


class ProviderCredentialDecryptionError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ProviderCredentialStatus:
    configured: bool
    version: int | None
    updated_at: datetime | None
    all_time: UsageTotals
    current_month: UsageTotals


class ProviderCredentialCipher:
    def __init__(self, settings: ProviderCredentialCipherSettings) -> None:
        configured = settings.provider_credential_master_key
        if configured is None:
            raise ProviderCredentialConfigurationError(
                "Provider credential master key is not configured"
            )
        try:
            key = base64.b64decode(configured.get_secret_value(), validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ProviderCredentialConfigurationError(
                "Provider credential master key is invalid"
            ) from exc
        if len(key) != 32:
            raise ProviderCredentialConfigurationError("Provider credential master key is invalid")
        self._cipher = AESGCM(key)

    def encrypt(
        self,
        api_key: str,
        *,
        credential_id: UUID,
        user_id: UUID,
        version: int,
    ) -> tuple[bytes, bytes]:
        nonce = os.urandom(12)
        ciphertext = self._cipher.encrypt(
            nonce,
            api_key.encode(),
            self._aad(
                credential_id=credential_id,
                user_id=user_id,
                version=version,
            ),
        )
        return nonce, ciphertext

    def decrypt(self, credential: ProviderCredentialVersionModel) -> str:
        if credential.algorithm != ALGORITHM:
            raise ProviderCredentialDecryptionError(
                "Unsupported Provider credential encryption algorithm"
            )
        try:
            plaintext = self._cipher.decrypt(
                credential.nonce,
                credential.ciphertext,
                self._aad(
                    credential_id=credential.id,
                    user_id=credential.user_id,
                    version=credential.version,
                ),
            )
            return plaintext.decode()
        except (InvalidTag, UnicodeDecodeError, ValueError) as exc:
            raise ProviderCredentialDecryptionError(
                "Provider credential could not be decrypted"
            ) from exc

    @staticmethod
    def _aad(*, credential_id: UUID, user_id: UUID, version: int) -> bytes:
        return (
            f"novel-platform:provider-credential:v1:{user_id}:{credential_id}:"
            f"{PROVIDER_ID}:{version}"
        ).encode()


class ProviderCredentialService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self.settings = settings
        self.credentials = ProviderCredentialRepository(session)
        self.audit = AuthRepository(session)

    async def status(self, user_id: UUID) -> ProviderCredentialStatus:
        current = await self.credentials.current(user_id)
        latest = current or await self.credentials.latest(user_id)
        all_time, current_month = await self.credentials.all_time_and_current_month(user_id)
        updated_at: datetime | None = None
        if latest is not None:
            lifecycle_times = [
                item
                for item in (
                    latest.created_at,
                    latest.retired_at,
                    latest.revoked_at,
                )
                if item is not None
            ]
            updated_at = max(lifecycle_times)
        return ProviderCredentialStatus(
            configured=current is not None,
            version=current.version if current is not None else None,
            updated_at=updated_at,
            all_time=all_time,
            current_month=current_month,
        )

    async def rotate(
        self,
        actor: AuthContext,
        api_key: str,
    ) -> ProviderCredentialStatus:
        value = self._validate_api_key(api_key)
        cipher = self._cipher()
        await self.credentials.lock_user(actor.user.id)
        now = datetime.now(UTC)
        current = await self.credentials.current(actor.user.id, for_update=True)
        version = await self.credentials.next_version(actor.user.id)
        credential_id = uuid4()
        nonce, ciphertext = cipher.encrypt(
            value,
            credential_id=credential_id,
            user_id=actor.user.id,
            version=version,
        )
        if current is not None:
            current.retired_at = now
        await self.credentials.add(
            ProviderCredentialVersionModel(
                id=credential_id,
                user_id=actor.user.id,
                provider=PROVIDER_ID,
                version=version,
                algorithm=ALGORITHM,
                nonce=nonce,
                ciphertext=ciphertext,
                created_at=now,
            )
        )
        self.audit.audit(
            "provider_credential_updated",
            "success",
            actor_user_id=actor.user.id,
            subject_user_id=actor.user.id,
            session_id=actor.session.id,
            device_id=actor.device.id,
            access_credential_id=actor.session.access_credential_id,
            metadata={
                "provider": PROVIDER_ID,
                "version": version,
                "rotated": current is not None,
            },
        )
        await self.session.commit()
        return await self.status(actor.user.id)

    async def remove(self, actor: AuthContext) -> None:
        await self.credentials.lock_user(actor.user.id)
        now = datetime.now(UTC)
        revoked_count = await self.credentials.revoke_all(actor.user.id, now=now)
        self.audit.audit(
            "provider_credential_removed",
            "success",
            actor_user_id=actor.user.id,
            subject_user_id=actor.user.id,
            session_id=actor.session.id,
            device_id=actor.device.id,
            access_credential_id=actor.session.access_credential_id,
            metadata={
                "provider": PROVIDER_ID,
                "revoked_version_count": revoked_count,
            },
        )
        await self.session.commit()

    async def current_for_run(self, user_id: UUID) -> ProviderCredentialVersionModel:
        self._cipher()
        credential = await self.credentials.current(user_id)
        if credential is None:
            raise ApplicationError(
                "provider_credential_required",
                "请先配置自己的模型服务 API Key。",
                status_code=409,
            )
        return credential

    async def usable_bound_credential(
        self,
        credential_scope: UUID,
    ) -> ProviderCredentialVersionModel:
        credential = await self.credentials.resolve_usable(credential_scope)
        if credential is None:
            raise ApplicationError(
                "provider_credential_unavailable",
                "该翻译任务绑定的模型凭据已不可用。",
                status_code=409,
            )
        return credential

    def decrypt(self, credential: ProviderCredentialVersionModel) -> str:
        return self._cipher().decrypt(credential)

    def _cipher(self) -> ProviderCredentialCipher:
        try:
            return ProviderCredentialCipher(self.settings)
        except ProviderCredentialConfigurationError as exc:
            raise ApplicationError(
                "provider_credential_store_unavailable",
                "模型凭据库尚未完成安全配置。",
                status_code=503,
            ) from exc

    @staticmethod
    def _validate_api_key(api_key: str) -> str:
        value = api_key.strip()
        if (
            not value
            or len(value) > 8192
            or any(ord(character) < 32 or ord(character) == 127 for character in value)
        ):
            raise ApplicationError(
                "invalid_provider_credential",
                "模型服务 API Key 无效。",
                status_code=422,
            )
        return value
