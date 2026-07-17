from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from pydantic import SecretStr, ValidationError

from novel_platform.application.auth.security import TokenService
from novel_platform.application.errors import ApplicationError
from novel_platform.config import Settings
from novel_platform.domain.auth.rules import (
    normalize_display_name,
    normalize_username,
)
from novel_platform.domain.errors import DomainRuleViolation


def secure_settings() -> Settings:
    return Settings(
        auth_jwt_secret=SecretStr("jwt-secret-abcdefghijklmnopqrstuvwxyz-01"),
        auth_hash_secret=SecretStr("hash-secret-abcdefghijklmnopqrstuvwxyz-1"),
        auth_credential_hash_secret=SecretStr("credential-secret-abcdefghijklmnopqrstuvwxyz-1"),
    )


def test_username_normalization_is_unicode_aware_and_case_insensitive() -> None:
    username, normalized = normalize_username("  \uff32eader-一  ")
    assert username == "Reader-一"
    assert normalized == "reader-一"
    assert normalize_display_name("  阅读者  ") == "阅读者"


@pytest.mark.parametrize("username", ["ab", "name with space", "name!", "_" * 65])
def test_invalid_username_is_rejected(username: str) -> None:
    with pytest.raises(DomainRuleViolation) as error:
        normalize_username(username)
    assert error.value.code == "invalid_username"


def test_access_device_and_recovery_credentials_are_random_and_domain_separated() -> None:
    service = TokenService(secure_settings())
    first, first_hash, hint = service.new_access_credential()
    second, second_hash, _ = service.new_access_credential()
    assert first.startswith("npa_")
    assert len(first.removeprefix("npa_")) >= 43
    assert first != second
    assert first_hash != second_hash
    assert service.hash_access_credential(first) == first_hash
    assert service.hash_recovery_credential(first) != first_hash
    assert service.hash_device_secret(first) not in {first_hash, second_hash}
    assert first not in hint
    assert hint.endswith(first[-6:])


def test_access_token_validates_signature_issuer_audience_and_expiry() -> None:
    service = TokenService(secure_settings())
    user_id = uuid4()
    session_id = uuid4()
    device_id = uuid4()
    token, ttl = service.issue_access_token(
        user_id=user_id,
        session_id=session_id,
        device_id=device_id,
        role="admin",
    )
    assert ttl == 900
    claims = service.decode_access_token(token)
    assert (claims.user_id, claims.session_id, claims.device_id) == (
        user_id,
        session_id,
        device_id,
    )
    header, payload, signature = token.split(".")
    forged_signature = f"{'a' if signature[0] != 'a' else 'b'}{signature[1:]}"
    forged = ".".join((header, payload, forged_signature))
    with pytest.raises(ApplicationError) as forged_error:
        service.decode_access_token(forged)
    assert forged_error.value.code == "invalid_access_token"
    expired, _ = service.issue_access_token(
        user_id=user_id,
        session_id=session_id,
        device_id=device_id,
        role="admin",
        now=datetime.now(UTC) - timedelta(hours=1),
    )
    with pytest.raises(ApplicationError) as expired_error:
        service.decode_access_token(expired)
    assert expired_error.value.code == "access_token_expired"


def test_production_rejects_placeholder_short_or_shared_secrets() -> None:
    with pytest.raises(ValidationError):
        Settings(environment="production", auth_cookie_secure=True)
    with pytest.raises(ValidationError):
        Settings(
            auth_jwt_secret=SecretStr("same-secret-abcdefghijklmnopqrstuvwxyz"),
            auth_hash_secret=SecretStr("another-secret-abcdefghijklmnopqrstuvwxyz"),
            auth_credential_hash_secret=SecretStr("same-secret-abcdefghijklmnopqrstuvwxyz"),
        )


def test_production_requires_https_webauthn_and_closed_openapi() -> None:
    settings = Settings(
        environment="production",
        auth_cookie_secure=True,
        auth_cookie_samesite="strict",
        openapi_enabled=False,
        auth_jwt_secret=SecretStr("jwt-random-secret-abcdefghijklmnopqrstuvwxyz"),
        auth_hash_secret=SecretStr("hash-random-secret-abcdefghijklmnopqrstuvwxyz"),
        auth_credential_hash_secret=SecretStr(
            "credential-random-secret-abcdefghijklmnopqrstuvwxyz"
        ),
        webauthn_rp_id="reader.example.com",
        webauthn_origins=["https://reader.example.com"],
    )
    assert settings.openapi_enabled is False


def test_protected_environments_require_samesite_strict_cookies() -> None:
    base = {
        "auth_cookie_secure": True,
        "auth_jwt_secret": SecretStr("jwt-random-secret-abcdefghijklmnopqrstuvwxyz"),
        "auth_hash_secret": SecretStr("hash-random-secret-abcdefghijklmnopqrstuvwxyz"),
        "auth_credential_hash_secret": SecretStr(
            "credential-random-secret-abcdefghijklmnopqrstuvwxyz"
        ),
        "webauthn_rp_id": "reader.example.com",
        "webauthn_origins": ["https://reader.example.com"],
    }
    with pytest.raises(ValidationError):
        Settings(environment="production", openapi_enabled=False, **base)  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        Settings(
            environment="staging",
            trusted_hosts=["staging.example"],
            **base,  # type: ignore[arg-type]
        )
    relaxed = Settings(
        environment="development",
        auth_cookie_samesite="lax",
        auth_jwt_secret=SecretStr("jwt-random-secret-abcdefghijklmnopqrstuvwxyz"),
        auth_hash_secret=SecretStr("hash-random-secret-abcdefghijklmnopqrstuvwxyz"),
        auth_credential_hash_secret=SecretStr(
            "credential-random-secret-abcdefghijklmnopqrstuvwxyz"
        ),
    )
    assert relaxed.auth_cookie_samesite == "lax"


def test_staging_requires_strong_secrets_and_explicit_hosts_but_can_use_http() -> None:
    with pytest.raises(ValidationError):
        Settings(environment="staging", auth_cookie_samesite="strict")
    settings = Settings(
        environment="staging",
        auth_cookie_secure=False,
        auth_cookie_samesite="strict",
        trusted_hosts=["staging.example"],
        auth_jwt_secret=SecretStr("jwt-random-secret-abcdefghijklmnopqrstuvwxyz"),
        auth_hash_secret=SecretStr("hash-random-secret-abcdefghijklmnopqrstuvwxyz"),
        auth_credential_hash_secret=SecretStr(
            "credential-random-secret-abcdefghijklmnopqrstuvwxyz"
        ),
    )
    assert settings.auth_cookie_secure is False
    with pytest.raises(ValidationError):
        Settings(
            environment="staging",
            auth_cookie_samesite="strict",
            trusted_hosts=["*"],
            auth_jwt_secret=SecretStr("jwt-random-secret-abcdefghijklmnopqrstuvwxyz"),
            auth_hash_secret=SecretStr("hash-random-secret-abcdefghijklmnopqrstuvwxyz"),
            auth_credential_hash_secret=SecretStr(
                "credential-random-secret-abcdefghijklmnopqrstuvwxyz"
            ),
        )
