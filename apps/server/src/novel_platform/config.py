from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEVELOPMENT_JWT_SECRET = "development-jwt-secret-change-me-0001"
DEVELOPMENT_HASH_SECRET = "development-hash-secret-change-me-001"
DEVELOPMENT_CREDENTIAL_HASH_SECRET = "development-credential-hash-secret-change-me-001"
PLACEHOLDER_MARKERS = ("change-me", "placeholder", "example", "replace-with")


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
    linguaspindle_version_range: str = ">=0.3.1,<0.4.0"
    linguaspindle_provider_id: str = Field(
        default="openai-compatible", min_length=1, max_length=120
    )
    linguaspindle_profile_id: str | None = Field(default=None, max_length=128)
    linguaspindle_connect_timeout_seconds: float = Field(default=3, gt=0, le=60)
    linguaspindle_read_timeout_seconds: float = Field(default=30, gt=0, le=600)
    linguaspindle_max_download_bytes: int = Field(default=104_857_600, ge=1, le=2_147_483_647)

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
        if self.linguaspindle_max_download_bytes > self.max_upload_bytes:
            raise ValueError("LINGUASPINDLE_MAX_DOWNLOAD_BYTES cannot exceed MAX_UPLOAD_BYTES")
        if self.linguaspindle_version_range != ">=0.3.1,<0.4.0":
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
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
