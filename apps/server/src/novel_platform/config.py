import base64
import binascii
import secrets
from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEVELOPMENT_JWT_SECRET = "development-jwt-secret-change-me-0001"
DEVELOPMENT_HASH_SECRET = "development-hash-secret-change-me-001"
DEVELOPMENT_CREDENTIAL_HASH_SECRET = "development-credential-hash-secret-change-me-001"
KNOWN_DEVELOPMENT_PROVIDER_CREDENTIAL_MASTER_KEY = bytes(32)
PLACEHOLDER_MARKERS = ("change-me", "placeholder", "example", "replace-with")


def normalize_provider_base_url(
    value: str,
    *,
    protected_environment: bool,
    setting_name: str,
) -> str:
    if not value or not value.isprintable():
        raise ValueError(f"{setting_name} must contain fixed HTTP(S) base URLs")
    normalized = value.strip().rstrip("/")
    parsed = urlsplit(normalized)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or ".." in parsed.path.split("/")
    ):
        raise ValueError(f"{setting_name} must contain fixed HTTP(S) base URLs")
    if protected_environment and parsed.scheme != "https":
        raise ValueError(f"staging/production {setting_name} must use HTTPS")
    return normalized


def normalize_provider_base_url_allowlist(
    values: list[str],
    *,
    protected_environment: bool,
) -> list[str]:
    normalized = [
        normalize_provider_base_url(
            value,
            protected_environment=protected_environment,
            setting_name="PROVIDER_RELAY_CUSTOM_ALLOWED_BASE_URLS",
        )
        for value in values
    ]
    if len(normalized) != len(set(normalized)):
        raise ValueError("PROVIDER_RELAY_CUSTOM_ALLOWED_BASE_URLS must be unique")
    return normalized


def _validate_provider_credential_master_key(
    value: SecretStr | None, *, protected_environment: bool
) -> None:
    if value is None:
        return
    try:
        decoded_master_key = base64.b64decode(value.get_secret_value(), validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("PROVIDER_CREDENTIAL_MASTER_KEY must be strict base64") from exc
    if len(decoded_master_key) != 32:
        raise ValueError("PROVIDER_CREDENTIAL_MASTER_KEY must decode to exactly 32 bytes")
    if (
        protected_environment
        and decoded_master_key == KNOWN_DEVELOPMENT_PROVIDER_CREDENTIAL_MASTER_KEY
    ):
        raise ValueError(
            "staging/production PROVIDER_CREDENTIAL_MASTER_KEY cannot use the known development key"
        )


class DatabaseSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = Field(
        default="postgresql+psycopg://novel_platform:novel_platform@localhost:5432/novel_platform"
    )


@lru_cache
def get_database_settings() -> DatabaseSettings:
    return DatabaseSettings()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Novel Platform API"
    environment: str = "development"
    log_level: str = "INFO"
    database_url: str = Field(
        default="postgresql+psycopg://novel_platform:novel_platform@localhost:5432/novel_platform"
    )
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])
    trusted_hosts: list[str] = Field(
        default_factory=lambda: ["localhost", "127.0.0.1", "test", "testserver"]
    )
    trust_proxy_headers: bool = False
    openapi_enabled: bool = True

    library_storage_root: Path = Path("/tmp/novel-platform/library")
    max_upload_bytes: int = Field(default=104_857_600, ge=1, le=2_147_483_647)
    max_epub_uncompressed_bytes: int = Field(default=524_288_000, ge=1)
    max_epub_entry_count: int = Field(default=10_000, ge=1, le=1_000_000)
    max_cover_bytes: int = Field(default=20_971_520, ge=1)
    max_cover_pixels: int = Field(default=40_000_000, ge=1)
    library_temporary_ttl_hours: int = Field(default=24, ge=1, le=24 * 30)

    linguaspindle_enabled: bool = False
    linguaspindle_base_url: str = "http://linguaspindle:8765"
    linguaspindle_version_range: str = ">=0.3.2,<0.4.0"
    linguaspindle_provider_id: str = Field(
        default="openai-compatible", min_length=1, max_length=120
    )
    linguaspindle_profile_id: str | None = Field(default=None, max_length=128)
    linguaspindle_connect_timeout_seconds: float = Field(default=3, gt=0, le=60)
    linguaspindle_read_timeout_seconds: float = Field(default=30, gt=0, le=600)
    linguaspindle_max_download_bytes: int = Field(default=104_857_600, ge=1, le=2_147_483_647)

    provider_credential_master_key: SecretStr | None = None
    provider_relay_service_secret: SecretStr | None = None
    provider_relay_internal_url: str = "http://novel-provider-relay:8790"
    provider_relay_upstream_base_url: str = "https://api.openai.com/v1"
    provider_relay_allowed_models: list[str] = Field(
        default_factory=lambda: ["gpt-4.1-mini"],
        min_length=1,
        max_length=100,
    )
    provider_relay_custom_allowed_base_urls: list[str] = Field(
        default_factory=list,
        max_length=100,
    )
    provider_relay_connect_timeout_seconds: float = Field(default=5, gt=0, le=60)
    provider_relay_read_timeout_seconds: float = Field(default=120, gt=0, le=600)
    provider_relay_max_request_bytes: int = Field(default=1_048_576, ge=1, le=16_777_216)
    provider_relay_max_response_bytes: int = Field(default=4_194_304, ge=1, le=67_108_864)

    auth_jwt_secret: SecretStr = SecretStr(DEVELOPMENT_JWT_SECRET)
    auth_hash_secret: SecretStr = SecretStr(DEVELOPMENT_HASH_SECRET)
    auth_credential_hash_secret: SecretStr = SecretStr(DEVELOPMENT_CREDENTIAL_HASH_SECRET)
    auth_access_token_ttl_seconds: int = Field(default=900, ge=60, le=86_400)
    auth_refresh_token_ttl_days: int = Field(default=30, ge=1, le=365)
    auth_cookie_name: str = "novel_refresh"
    auth_device_cookie_name: str = "novel_device"
    auth_cookie_secure: bool = False
    auth_cookie_samesite: Literal["lax", "strict", "none"] = "lax"
    auth_cookie_domain: str | None = None
    auth_device_cookie_ttl_days: int = Field(default=365, ge=1, le=3650)
    auth_issuer: str = "novel-platform"
    auth_audience: str = "novel-platform-client"
    auth_login_max_failures: int = Field(default=5, ge=1, le=100)
    auth_login_window_seconds: int = Field(default=600, ge=1, le=86_400)
    auth_login_block_seconds: int = Field(default=900, ge=1, le=86_400)
    admin_recovery_ttl_minutes: int = Field(default=15, ge=5, le=60)
    webauthn_rp_id: str = "localhost"
    webauthn_rp_name: str = "个人数字阅读与藏书整理"
    webauthn_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])
    webauthn_challenge_ttl_seconds: int = Field(default=300, ge=60, le=900)

    @model_validator(mode="after")
    def validate_auth_configuration(self) -> "Settings":
        jwt_secret = self.auth_jwt_secret.get_secret_value()
        hash_secret = self.auth_hash_secret.get_secret_value()
        credential_hash_secret = self.auth_credential_hash_secret.get_secret_value()
        configured_secrets = [jwt_secret, hash_secret, credential_hash_secret]
        if len(set(configured_secrets)) != len(configured_secrets):
            raise ValueError("authentication secrets must be independent")
        protected_environment = self.environment.lower() in {"production", "staging"}
        if protected_environment:
            for value in configured_secrets:
                is_placeholder = any(marker in value.lower() for marker in PLACEHOLDER_MARKERS)
                if len(value.encode()) < 32 or is_placeholder:
                    raise ValueError(
                        "staging/production authentication secrets must be random "
                        "and at least 32 bytes"
                    )
            if not self.trusted_hosts or "*" in self.trusted_hosts:
                raise ValueError("staging/production requires an explicit trusted host allow-list")
            if self.auth_cookie_samesite != "strict":
                raise ValueError(
                    "staging/production requires SameSite=Strict authentication cookies"
                )
        if self.environment.lower() == "production":
            if not self.auth_cookie_secure:
                raise ValueError("production requires secure refresh cookies")
            if self.openapi_enabled:
                raise ValueError("production requires OPENAPI_ENABLED=false")
            if self.webauthn_rp_id in {"localhost", "127.0.0.1"}:
                raise ValueError("production requires a stable WebAuthn RP ID")
            if not self.webauthn_origins or any(
                not origin.lower().startswith("https://") for origin in self.webauthn_origins
            ):
                raise ValueError("production WebAuthn origins must use HTTPS")
        if self.auth_cookie_samesite == "none" and not self.auth_cookie_secure:
            raise ValueError("SameSite=None requires secure refresh cookies")
        if self.auth_cookie_domain == "":
            self.auth_cookie_domain = None
        if not self.webauthn_origins:
            raise ValueError("at least one WebAuthn origin is required")
        if not self.library_storage_root.is_absolute():
            raise ValueError("LIBRARY_STORAGE_ROOT must be an absolute path")
        if self.library_storage_root == Path(self.library_storage_root.anchor):
            raise ValueError("LIBRARY_STORAGE_ROOT cannot be a filesystem root")
        if self.max_epub_uncompressed_bytes < self.max_upload_bytes:
            raise ValueError("MAX_EPUB_UNCOMPRESSED_BYTES must be at least MAX_UPLOAD_BYTES")
        if (
            self.linguaspindle_enabled
            and self.linguaspindle_max_download_bytes > self.max_upload_bytes
        ):
            raise ValueError("LINGUASPINDLE_MAX_DOWNLOAD_BYTES cannot exceed MAX_UPLOAD_BYTES")
        if self.linguaspindle_version_range != ">=0.3.2,<0.4.0":
            raise ValueError("unsupported LINGUASPINDLE_VERSION_RANGE")
        parsed_lingua_url = urlsplit(self.linguaspindle_base_url)
        if (
            parsed_lingua_url.scheme not in {"http", "https"}
            or not parsed_lingua_url.hostname
            or parsed_lingua_url.username is not None
            or parsed_lingua_url.password is not None
            or parsed_lingua_url.query
            or parsed_lingua_url.fragment
            or parsed_lingua_url.path not in {"", "/"}
        ):
            raise ValueError("LINGUASPINDLE_BASE_URL must be one fixed HTTP(S) origin")
        if (
            protected_environment
            and self.linguaspindle_enabled
            and parsed_lingua_url.hostname
            in {
                "localhost",
                "127.0.0.1",
                "::1",
            }
        ):
            raise ValueError("staging/production LinguaSpindle URL cannot use loopback")
        self.linguaspindle_base_url = self.linguaspindle_base_url.rstrip("/")
        if self.linguaspindle_profile_id == "":
            self.linguaspindle_profile_id = None
        self._validate_provider_credential_configuration(protected_environment)
        return self

    def _validate_provider_credential_configuration(self, protected_environment: bool) -> None:
        master_key = (
            self.provider_credential_master_key.get_secret_value()
            if self.provider_credential_master_key is not None
            else None
        )
        _validate_provider_credential_master_key(
            self.provider_credential_master_key,
            protected_environment=protected_environment,
        )

        relay_secret = (
            self.provider_relay_service_secret.get_secret_value()
            if self.provider_relay_service_secret is not None
            else None
        )
        if relay_secret is not None and len(relay_secret.encode()) < 32:
            raise ValueError("PROVIDER_RELAY_SERVICE_SECRET must be at least 32 bytes")
        if protected_environment and self.linguaspindle_enabled:
            if master_key is None:
                raise ValueError("enabled translation requires PROVIDER_CREDENTIAL_MASTER_KEY")
        if protected_environment and relay_secret is not None:
            if any(marker in relay_secret.lower() for marker in PLACEHOLDER_MARKERS):
                raise ValueError("PROVIDER_RELAY_SERVICE_SECRET cannot be a placeholder")

        models = [model.strip() for model in self.provider_relay_allowed_models]
        if (
            not models
            or len(models) != len(set(models))
            or any(not model or len(model) > 120 or not model.isprintable() for model in models)
        ):
            raise ValueError(
                "PROVIDER_RELAY_ALLOWED_MODELS must contain unique non-blank model IDs"
            )
        self.provider_relay_allowed_models = models
        self.provider_relay_custom_allowed_base_urls = normalize_provider_base_url_allowlist(
            self.provider_relay_custom_allowed_base_urls,
            protected_environment=protected_environment,
        )

        self.provider_relay_upstream_base_url = normalize_provider_base_url(
            self.provider_relay_upstream_base_url,
            protected_environment=protected_environment,
            setting_name="PROVIDER_RELAY_UPSTREAM_BASE_URL",
        )

        parsed_internal = urlsplit(self.provider_relay_internal_url)
        if (
            parsed_internal.scheme not in {"http", "https"}
            or not parsed_internal.hostname
            or parsed_internal.username is not None
            or parsed_internal.password is not None
            or parsed_internal.query
            or parsed_internal.fragment
            or parsed_internal.path not in {"", "/"}
        ):
            raise ValueError("PROVIDER_RELAY_INTERNAL_URL must be one fixed HTTP(S) origin")
        if protected_environment and parsed_internal.hostname in {"localhost", "127.0.0.1", "::1"}:
            raise ValueError("staging/production Provider relay URL cannot use loopback")
        self.provider_relay_internal_url = self.provider_relay_internal_url.rstrip("/")


@lru_cache
def get_settings() -> Settings:
    return Settings()


class ProviderRelaySettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    environment: str = "development"
    log_level: str = "INFO"
    database_url: str = Field(
        default="postgresql+psycopg://novel_platform:novel_platform@localhost:5432/novel_platform"
    )
    provider_credential_master_key: SecretStr | None = None
    provider_relay_service_secret: SecretStr | None = None
    provider_relay_upstream_base_url: str = "https://api.openai.com/v1"
    provider_relay_allowed_models: list[str] = Field(
        default_factory=lambda: ["gpt-4.1-mini"],
        min_length=1,
        max_length=100,
    )
    provider_relay_custom_allowed_base_urls: list[str] = Field(
        default_factory=list,
        max_length=100,
    )
    provider_relay_connect_timeout_seconds: float = Field(default=5, gt=0, le=60)
    provider_relay_read_timeout_seconds: float = Field(default=120, gt=0, le=600)
    provider_relay_max_request_bytes: int = Field(default=1_048_576, ge=1, le=16_777_216)
    provider_relay_max_response_bytes: int = Field(default=4_194_304, ge=1, le=67_108_864)

    @model_validator(mode="after")
    def validate_relay_configuration(self) -> "ProviderRelaySettings":
        protected_environment = self.environment.lower() in {"production", "staging"}
        master_key = (
            self.provider_credential_master_key.get_secret_value()
            if self.provider_credential_master_key is not None
            else None
        )
        _validate_provider_credential_master_key(
            self.provider_credential_master_key,
            protected_environment=protected_environment,
        )
        relay_secret = (
            self.provider_relay_service_secret.get_secret_value()
            if self.provider_relay_service_secret is not None
            else None
        )
        if relay_secret is not None and len(relay_secret.encode()) < 32:
            raise ValueError("PROVIDER_RELAY_SERVICE_SECRET must be at least 32 bytes")

        if protected_environment and (master_key is None or relay_secret is None):
            raise ValueError(
                "staging/production Provider relay requires master key and service secret"
            )
        if (
            protected_environment
            and master_key is not None
            and relay_secret is not None
            and secrets.compare_digest(master_key, relay_secret)
        ):
            raise ValueError(
                "staging/production Provider relay requires independent master and service secrets"
            )
        if (
            protected_environment
            and relay_secret is not None
            and any(marker in relay_secret.lower() for marker in PLACEHOLDER_MARKERS)
        ):
            raise ValueError("PROVIDER_RELAY_SERVICE_SECRET cannot be a placeholder")

        models = [model.strip() for model in self.provider_relay_allowed_models]
        if (
            not models
            or len(models) != len(set(models))
            or any(not model or len(model) > 120 or not model.isprintable() for model in models)
        ):
            raise ValueError(
                "PROVIDER_RELAY_ALLOWED_MODELS must contain unique non-blank model IDs"
            )
        self.provider_relay_allowed_models = models
        self.provider_relay_custom_allowed_base_urls = normalize_provider_base_url_allowlist(
            self.provider_relay_custom_allowed_base_urls,
            protected_environment=protected_environment,
        )

        self.provider_relay_upstream_base_url = normalize_provider_base_url(
            self.provider_relay_upstream_base_url,
            protected_environment=protected_environment,
            setting_name="PROVIDER_RELAY_UPSTREAM_BASE_URL",
        )
        return self


@lru_cache
def get_provider_relay_settings() -> ProviderRelaySettings:
    return ProviderRelaySettings()
