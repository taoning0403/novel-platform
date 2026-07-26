import base64
import binascii
import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final, Literal, Protocol, cast
from uuid import UUID, uuid4

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession

from novel_platform.application.auth.context import AuthContext
from novel_platform.application.errors import ApplicationError
from novel_platform.config import Settings, normalize_provider_base_url
from novel_platform.infrastructure.database.models import ProviderCredentialVersionModel
from novel_platform.infrastructure.repositories.auth import AuthRepository
from novel_platform.infrastructure.repositories.provider_credentials import (
    PROVIDER_ID,
    ProviderCredentialRepository,
    UsageTotals,
)

LEGACY_ALGORITHM: Final = "aes-256-gcm-v1"
ALGORITHM: Final = "aes-256-gcm-v2"
OPENAI_COMPATIBLE_PROVIDER: Final = "openai_compatible"
DEEPSEEK_PROVIDER: Final = "deepseek"
KIMI_PROVIDER: Final = "kimi"
CUSTOM_PROVIDER: Final = "custom"
SUPPORTED_PROVIDERS = frozenset(
    {
        OPENAI_COMPATIBLE_PROVIDER,
        DEEPSEEK_PROVIDER,
        KIMI_PROVIDER,
        CUSTOM_PROVIDER,
    }
)
type ProviderKind = Literal["openai_compatible", "deepseek", "kimi", "custom"]
OPENAI_BASE_URL: Final = "https://api.openai.com/v1"
OPENAI_DEFAULT_MODEL: Final = "gpt-4.1-mini"
DEEPSEEK_BASE_URL: Final = "https://api.deepseek.com/v1"
DEEPSEEK_DEFAULT_MODEL: Final = "deepseek-chat"
KIMI_BASE_URL: Final = "https://api.moonshot.cn/v1"
KIMI_DEFAULT_MODEL: Final = "kimi-k2.5"
PROVIDER_DISPLAY_NAMES: Final[dict[ProviderKind, str]] = {
    OPENAI_COMPATIBLE_PROVIDER: "OpenAI",
    DEEPSEEK_PROVIDER: "DeepSeek",
    KIMI_PROVIDER: "Kimi",
    CUSTOM_PROVIDER: "自定义 Provider",
}


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
    provider: ProviderKind
    provider_name: str
    base_url: str
    model: str
    thinking_enabled: bool
    version: int | None
    updated_at: datetime | None
    all_time: UsageTotals
    current_month: UsageTotals


@dataclass(frozen=True, slots=True)
class ProviderConfiguration:
    provider: ProviderKind
    provider_name: str | None
    base_url: str
    model: str
    thinking_enabled: bool


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
        provider: str,
        provider_name: str | None,
        base_url: str,
        model: str,
        thinking_enabled: bool,
    ) -> tuple[bytes, bytes]:
        nonce = os.urandom(12)
        ciphertext = self._cipher.encrypt(
            nonce,
            api_key.encode(),
            self._aad_v2(
                credential_id=credential_id,
                user_id=user_id,
                version=version,
                provider=provider,
                provider_name=provider_name,
                base_url=base_url,
                model=model,
                thinking_enabled=thinking_enabled,
            ),
        )
        return nonce, ciphertext

    def decrypt(self, credential: ProviderCredentialVersionModel) -> str:
        if credential.algorithm == LEGACY_ALGORITHM:
            aad = self._aad_v1(
                credential_id=credential.id,
                user_id=credential.user_id,
                version=credential.version,
            )
        elif credential.algorithm == ALGORITHM:
            aad = self._aad_v2(
                credential_id=credential.id,
                user_id=credential.user_id,
                version=credential.version,
                provider=credential.provider,
                provider_name=credential.provider_name,
                base_url=credential.base_url,
                model=credential.model,
                thinking_enabled=credential.thinking_enabled,
            )
        else:
            raise ProviderCredentialDecryptionError(
                "Unsupported Provider credential encryption algorithm"
            )
        try:
            plaintext = self._cipher.decrypt(
                credential.nonce,
                credential.ciphertext,
                aad,
            )
            return plaintext.decode()
        except (InvalidTag, UnicodeDecodeError, ValueError) as exc:
            raise ProviderCredentialDecryptionError(
                "Provider credential could not be decrypted"
            ) from exc

    @staticmethod
    def _aad_v1(*, credential_id: UUID, user_id: UUID, version: int) -> bytes:
        return (
            f"novel-platform:provider-credential:v1:{user_id}:{credential_id}:"
            f"{PROVIDER_ID}:{version}"
        ).encode()

    @staticmethod
    def _aad_v2(
        *,
        credential_id: UUID,
        user_id: UUID,
        version: int,
        provider: str,
        provider_name: str | None,
        base_url: str,
        model: str,
        thinking_enabled: bool,
    ) -> bytes:
        return json.dumps(
            {
                "contract": "novel-platform:provider-credential:v2",
                "base_url": base_url,
                "credential_id": str(credential_id),
                "model": model,
                "provider": provider,
                "provider_name": provider_name,
                "thinking_enabled": thinking_enabled,
                "user_id": str(user_id),
                "version": version,
            },
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
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
        projected = current or latest
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
        projected_provider = (
            cast(ProviderKind, projected.provider)
            if projected is not None and projected.algorithm != LEGACY_ALGORITHM
            else OPENAI_COMPATIBLE_PROVIDER
        )
        if projected is None:
            projected_base_url = OPENAI_BASE_URL
            projected_model = OPENAI_DEFAULT_MODEL
        elif projected.algorithm == LEGACY_ALGORITHM:
            projected_base_url = self.settings.provider_relay_upstream_base_url
            projected_model = self.settings.provider_relay_allowed_models[0]
        else:
            projected_base_url = projected.base_url
            projected_model = projected.model
        return ProviderCredentialStatus(
            configured=current is not None,
            provider=projected_provider,
            provider_name=(
                projected.provider_name
                if projected_provider == CUSTOM_PROVIDER
                and projected is not None
                and projected.provider_name is not None
                else PROVIDER_DISPLAY_NAMES[projected_provider]
            ),
            base_url=projected_base_url,
            model=projected_model,
            thinking_enabled=(
                current.thinking_enabled
                if current is not None and current.algorithm != LEGACY_ALGORITHM
                else False
            ),
            version=current.version if current is not None else None,
            updated_at=updated_at,
            all_time=all_time,
            current_month=current_month,
        )

    async def rotate(
        self,
        actor: AuthContext,
        api_key: str,
        *,
        provider: str = OPENAI_COMPATIBLE_PROVIDER,
        provider_name: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        thinking_enabled: bool = False,
    ) -> ProviderCredentialStatus:
        value = self._validate_api_key(api_key)
        configuration = self._provider_configuration(
            provider=provider,
            provider_name=provider_name,
            base_url=base_url,
            model=model,
            thinking_enabled=thinking_enabled,
        )
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
            provider=configuration.provider,
            provider_name=configuration.provider_name,
            base_url=configuration.base_url,
            model=configuration.model,
            thinking_enabled=configuration.thinking_enabled,
        )
        if current is not None:
            current.retired_at = now
        await self.credentials.add(
            ProviderCredentialVersionModel(
                id=credential_id,
                user_id=actor.user.id,
                provider=configuration.provider,
                provider_name=configuration.provider_name,
                base_url=configuration.base_url,
                model=configuration.model,
                thinking_enabled=configuration.thinking_enabled,
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
                "provider": configuration.provider,
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

    def _provider_configuration(
        self,
        *,
        provider: str,
        provider_name: str | None,
        base_url: str | None,
        model: str | None,
        thinking_enabled: bool,
    ) -> ProviderConfiguration:
        provider = provider.strip()
        if provider not in SUPPORTED_PROVIDERS:
            raise self._invalid_provider_configuration()

        normalized_model = self._normalize_model(model)
        if provider == CUSTOM_PROVIDER:
            normalized_name = self._normalize_provider_name(provider_name)
            if base_url is None:
                raise self._invalid_provider_configuration()
            try:
                normalized_base_url = normalize_provider_base_url(
                    base_url,
                    protected_environment=self.settings.environment.lower()
                    in {"production", "staging"},
                    setting_name="custom Provider base URL",
                )
            except ValueError as exc:
                raise self._invalid_provider_configuration() from exc
            if normalized_base_url not in self.settings.provider_relay_custom_allowed_base_urls:
                raise ApplicationError(
                    "provider_base_url_not_allowed",
                    "该自定义模型服务地址未获服务器允许。",
                    status_code=422,
                )
            if normalized_model is None:
                raise self._invalid_provider_configuration()
            self._validate_thinking_configuration(
                provider=CUSTOM_PROVIDER,
                model=normalized_model,
                thinking_enabled=thinking_enabled,
            )
            return ProviderConfiguration(
                provider=CUSTOM_PROVIDER,
                provider_name=normalized_name,
                base_url=normalized_base_url,
                model=normalized_model,
                thinking_enabled=thinking_enabled,
            )

        if provider_name is not None or base_url is not None:
            raise self._invalid_provider_configuration()
        presets = {
            OPENAI_COMPATIBLE_PROVIDER: (OPENAI_BASE_URL, OPENAI_DEFAULT_MODEL),
            DEEPSEEK_PROVIDER: (DEEPSEEK_BASE_URL, DEEPSEEK_DEFAULT_MODEL),
            KIMI_PROVIDER: (KIMI_BASE_URL, KIMI_DEFAULT_MODEL),
        }
        preset_base_url, default_model = presets[provider]
        effective_model = normalized_model or default_model
        provider_kind = cast(ProviderKind, provider)
        self._validate_thinking_configuration(
            provider=provider_kind,
            model=effective_model,
            thinking_enabled=thinking_enabled,
        )
        return ProviderConfiguration(
            provider=provider_kind,
            provider_name=None,
            base_url=preset_base_url,
            model=effective_model,
            thinking_enabled=thinking_enabled,
        )

    @staticmethod
    def _validate_thinking_configuration(
        *,
        provider: ProviderKind,
        model: str,
        thinking_enabled: bool,
    ) -> None:
        if provider in {OPENAI_COMPATIBLE_PROVIDER, CUSTOM_PROVIDER}:
            # OpenAI's reasoning_effort support and accepted values are model-specific;
            # a generic boolean must not silently claim a portable Chat Completions mapping.
            if thinking_enabled:
                raise ApplicationError(
                    "provider_thinking_not_supported",
                    "该模型服务不支持可验证的思考模式开关。",
                    status_code=422,
                )
            return
        if provider == DEEPSEEK_PROVIDER:
            is_reasoner = model == "deepseek-reasoner"
            if thinking_enabled != is_reasoner:
                raise ApplicationError(
                    "invalid_provider_thinking_configuration",
                    "DeepSeek 思考模式必须与 deepseek-reasoner 模型一致。",
                    status_code=422,
                )
            return
        if thinking_enabled and model != KIMI_DEFAULT_MODEL:
            raise ApplicationError(
                "provider_thinking_not_supported",
                "仅 kimi-k2.5 支持可验证的思考模式开关。",
                status_code=422,
            )

    @staticmethod
    def _normalize_provider_name(value: str | None) -> str:
        normalized = value.strip() if value is not None else ""
        if not normalized or len(normalized) > 120 or not normalized.isprintable():
            raise ProviderCredentialService._invalid_provider_configuration()
        return normalized

    @staticmethod
    def _normalize_model(value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized or len(normalized) > 120 or not normalized.isprintable():
            raise ProviderCredentialService._invalid_provider_configuration()
        return normalized

    @staticmethod
    def _invalid_provider_configuration() -> ApplicationError:
        return ApplicationError(
            "invalid_provider_configuration",
            "模型服务配置无效。",
            status_code=422,
        )

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
