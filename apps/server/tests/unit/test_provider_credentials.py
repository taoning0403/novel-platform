import base64
import logging
from typing import Any
from uuid import uuid4

import httpx
import pytest
from pydantic import SecretStr, ValidationError

from novel_platform import relay as provider_relay_module
from novel_platform.api.schemas import ProviderCredentialPut
from novel_platform.application.provider_credentials.service import (
    ALGORITHM,
    ProviderCredentialCipher,
    ProviderCredentialDecryptionError,
)
from novel_platform.config import DatabaseSettings, ProviderRelaySettings, Settings
from novel_platform.infrastructure.database.models import ProviderCredentialVersionModel
from novel_platform.relay import (
    ChatCompletionRequest,
    _sanitize_upstream_response,
    get_relay_session,
)
from novel_platform.relay import (
    app as provider_relay_app,
)


def settings_with_master_key() -> Settings:
    return Settings(
        provider_credential_master_key=SecretStr(base64.b64encode(bytes(range(32))).decode())
    )


def test_master_key_requires_strict_base64_encoding_of_exactly_32_bytes() -> None:
    with pytest.raises(ValidationError, match="strict base64"):
        Settings(provider_credential_master_key=SecretStr("not base64"))
    with pytest.raises(ValidationError, match="exactly 32 bytes"):
        Settings(provider_credential_master_key=SecretStr(base64.b64encode(b"too-short").decode()))


def test_protected_server_and_relay_reject_known_development_master_key() -> None:
    known_development_key = SecretStr(base64.b64encode(bytes(32)).decode())
    with pytest.raises(ValidationError, match="known development key"):
        Settings(
            environment="staging",
            auth_cookie_samesite="strict",
            auth_jwt_secret=SecretStr("j" * 32),
            auth_hash_secret=SecretStr("h" * 32),
            auth_credential_hash_secret=SecretStr("c" * 32),
            provider_credential_master_key=known_development_key,
        )
    with pytest.raises(ValidationError, match="known development key"):
        ProviderRelaySettings(
            environment="staging",
            provider_credential_master_key=known_development_key,
            provider_relay_service_secret=SecretStr("r" * 32),
        )

    assert (
        Settings(
            provider_credential_master_key=known_development_key
        ).provider_credential_master_key
        is not None
    )
    assert (
        ProviderRelaySettings(
            provider_credential_master_key=known_development_key
        ).provider_credential_master_key
        is not None
    )


def test_protected_relay_requires_independent_master_and_service_secrets() -> None:
    reused_secret = SecretStr(base64.b64encode(bytes(range(32))).decode())
    with pytest.raises(ValidationError, match="independent master and service secrets"):
        ProviderRelaySettings(
            environment="staging",
            provider_credential_master_key=reused_secret,
            provider_relay_service_secret=reused_secret,
        )


def test_migration_database_settings_do_not_require_application_or_relay_secrets() -> None:
    database = DatabaseSettings.model_validate(
        {
            "database_url": "postgresql+psycopg://migration-only@database/db",
            "environment": "staging",
            "linguaspindle_enabled": True,
            "provider_relay_service_secret": "must-be-ignored",
        }
    )
    assert database.database_url.endswith("@database/db")


def test_aes_gcm_round_trip_binds_ciphertext_to_credential_metadata() -> None:
    cipher = ProviderCredentialCipher(settings_with_master_key())
    credential_id = uuid4()
    user_id = uuid4()
    nonce, ciphertext = cipher.encrypt(
        "sk-user-owned-value",
        credential_id=credential_id,
        user_id=user_id,
        version=1,
    )
    stored = ProviderCredentialVersionModel(
        id=credential_id,
        user_id=user_id,
        provider="openai_compatible",
        version=1,
        algorithm=ALGORITHM,
        nonce=nonce,
        ciphertext=ciphertext,
    )
    assert cipher.decrypt(stored) == "sk-user-owned-value"
    assert stored.ciphertext != b"sk-user-owned-value"

    stored.version = 2
    with pytest.raises(ProviderCredentialDecryptionError):
        cipher.decrypt(stored)


def test_provider_key_validation_errors_do_not_render_the_secret() -> None:
    secret = "sk-" + ("sensitive" * 2000)
    with pytest.raises(ValidationError) as failure:
        ProviderCredentialPut.model_validate({"api_key": secret})
    assert secret not in str(failure.value)


def test_relay_accepts_only_bounded_non_streaming_chat_completion_fields() -> None:
    payload = ChatCompletionRequest.model_validate(
        {
            "model": "gpt-4.1-mini",
            "messages": [
                {"role": "system", "content": "Translate."},
                {"role": "user", "content": "正文"},
            ],
            "temperature": 0,
        }
    )
    assert payload.stream is False
    with pytest.raises(ValidationError):
        ChatCompletionRequest.model_validate(
            {
                "model": "gpt-4.1-mini",
                "messages": [{"role": "user", "content": "正文"}],
                "stream": True,
            }
        )
    with pytest.raises(ValidationError):
        ChatCompletionRequest.model_validate(
            {
                "model": "gpt-4.1-mini",
                "messages": [{"role": "user", "content": "正文"}],
                "api_key": "must-never-be-forwarded",
            }
        )


def test_relay_sanitizes_success_to_text_model_and_token_usage_only() -> None:
    sanitized, usage = _sanitize_upstream_response(
        {
            "id": "provider-private-id",
            "model": "gpt-4.1-mini-2026-01-01",
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": "Translated text",
                        "refusal": None,
                    },
                    "finish_reason": "stop",
                    "logprobs": {"private": "value"},
                }
            ],
            "usage": {
                "prompt_tokens": 10,
                "completion_tokens": 4,
                "total_tokens": 14,
                "prompt_tokens_details": {"cached_tokens": 2},
            },
            "system_fingerprint": "private",
        },
        requested_model="gpt-4.1-mini",
        forbidden_secret="sk-must-not-be-reflected",
    )
    assert sanitized == {
        "model": "gpt-4.1-mini-2026-01-01",
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": "Translated text",
                },
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": 10,
            "completion_tokens": 4,
            "total_tokens": 14,
        },
    }
    assert usage == sanitized["usage"]


@pytest.mark.parametrize("field", ["content", "model", "nested"])
def test_relay_rejects_success_responses_that_reflect_the_provider_key(field: str) -> None:
    secret = "sk-reader-owned-never-persist"
    payload: dict[str, Any] = {
        "model": "gpt-4.1-mini",
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": "Translated text",
                }
            }
        ],
    }
    if field == "content":
        payload["choices"][0]["message"]["content"] = f"Translated {secret}"
    elif field == "model":
        payload["model"] = f"model-{secret}"
    else:
        payload["private"] = {"debug": f"Bearer {secret}"}

    with pytest.raises(ValueError, match="forbidden secret"):
        _sanitize_upstream_response(
            payload,
            requested_model="gpt-4.1-mini",
            forbidden_secret=secret,
        )


async def test_relay_suppresses_unhandled_exception_values_from_response_and_logs(
    caplog: pytest.LogCaptureFixture,
) -> None:
    private_value = f"{uuid4()}:job-{uuid4()}:sk-never-log"

    async def failing_session() -> None:
        raise RuntimeError(f"database bind parameters: {private_value}")

    provider_relay_app.dependency_overrides[get_relay_session] = failing_session
    transport = httpx.ASGITransport(app=provider_relay_app, raise_app_exceptions=False)
    try:
        with caplog.at_level(logging.ERROR, logger="novel_platform.provider_relay"):
            async with httpx.AsyncClient(
                transport=transport,
                base_url="http://provider-relay",
            ) as client:
                response = await client.post("/v1/chat/completions")
    finally:
        provider_relay_app.dependency_overrides.clear()
        provider_relay_module.app.state.upstream_transport = None

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "provider_relay_unavailable"
    assert private_value not in response.text
    assert private_value not in caplog.text
    assert "RuntimeError" in caplog.text
