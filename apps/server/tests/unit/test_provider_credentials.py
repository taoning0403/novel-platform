import base64
import json
import logging
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from pydantic import SecretStr, ValidationError
from sqlalchemy import CheckConstraint, Table

from novel_platform import relay as provider_relay_module
from novel_platform.api.schemas import ProviderCredentialPut
from novel_platform.application.errors import ApplicationError
from novel_platform.application.provider_credentials.service import (
    ALGORITHM,
    LEGACY_ALGORITHM,
    ProviderCredentialCipher,
    ProviderCredentialDecryptionError,
    ProviderCredentialService,
)
from novel_platform.application.translations.service import TranslationRunService
from novel_platform.config import DatabaseSettings, ProviderRelaySettings, Settings
from novel_platform.infrastructure.database.models import ProviderCredentialVersionModel
from novel_platform.infrastructure.integrations.linguaspindle import LinguaServiceStatus
from novel_platform.infrastructure.repositories.provider_credentials import UsageTotals
from novel_platform.relay import (
    ChatCompletionRequest,
    _bound_provider_destination,
    _call_upstream,
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


def test_protected_legacy_upstream_accepts_non_official_https_base_url() -> None:
    master_key = SecretStr(base64.b64encode(bytes(range(32))).decode())
    relay_settings = ProviderRelaySettings(
        environment="staging",
        provider_credential_master_key=master_key,
        provider_relay_service_secret=SecretStr("r" * 32),
        provider_relay_upstream_base_url="https://operator.example/v1/",
    )
    server_settings = Settings(
        environment="staging",
        auth_cookie_samesite="strict",
        auth_jwt_secret=SecretStr("j" * 32),
        auth_hash_secret=SecretStr("h" * 32),
        auth_credential_hash_secret=SecretStr("c" * 32),
        provider_credential_master_key=master_key,
        provider_relay_service_secret=SecretStr("r" * 32),
        provider_relay_upstream_base_url="https://operator.example/v1/",
    )
    assert relay_settings.provider_relay_upstream_base_url == "https://operator.example/v1"
    assert server_settings.provider_relay_upstream_base_url == "https://operator.example/v1"

    with pytest.raises(ValidationError, match="must use HTTPS"):
        ProviderRelaySettings(
            environment="staging",
            provider_credential_master_key=master_key,
            provider_relay_service_secret=SecretStr("r" * 32),
            provider_relay_upstream_base_url="http://operator.example/v1",
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
        provider="custom",
        provider_name="私有模型",
        base_url="https://provider.example/v1",
        model="private-model",
        thinking_enabled=False,
    )
    stored = ProviderCredentialVersionModel(
        id=credential_id,
        user_id=user_id,
        provider="custom",
        provider_name="私有模型",
        base_url="https://provider.example/v1",
        model="private-model",
        thinking_enabled=False,
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
    stored.version = 1
    stored.base_url = "https://attacker.example/v1"
    with pytest.raises(ProviderCredentialDecryptionError):
        cipher.decrypt(stored)
    stored.base_url = "https://provider.example/v1"
    stored.thinking_enabled = True
    with pytest.raises(ProviderCredentialDecryptionError):
        cipher.decrypt(stored)


def test_legacy_v1_decryption_and_relay_destination_ignore_migrated_defaults() -> None:
    cipher = ProviderCredentialCipher(settings_with_master_key())
    credential_id = uuid4()
    user_id = uuid4()
    nonce = bytes(range(12))
    ciphertext = cipher._cipher.encrypt(
        nonce,
        b"sk-legacy-value",
        cipher._aad_v1(
            credential_id=credential_id,
            user_id=user_id,
            version=1,
        ),
    )
    stored = ProviderCredentialVersionModel(
        id=credential_id,
        user_id=user_id,
        provider="openai_compatible",
        provider_name=None,
        base_url="https://migration-default.invalid/v1",
        model="migration-default-model",
        thinking_enabled=False,
        version=1,
        algorithm=LEGACY_ALGORITHM,
        nonce=nonce,
        ciphertext=ciphertext,
    )
    assert cipher.decrypt(stored) == "sk-legacy-value"

    relay_settings = ProviderRelaySettings(
        provider_relay_upstream_base_url="https://operator-current.example/v1",
        provider_relay_allowed_models=["operator-current-model"],
    )
    assert _bound_provider_destination(
        stored,
        "operator-current-model",
        relay_settings,
    ) == ("https://operator-current.example/v1", "operator-current-model")


def test_legacy_v1_run_snapshot_ignores_migrated_routing_and_thinking_columns() -> None:
    settings = Settings(
        provider_relay_upstream_base_url="https://operator-current.example/v1",
        provider_relay_allowed_models=["operator-current-model"],
    )
    service = object.__new__(TranslationRunService)
    service.settings = settings
    credential = ProviderCredentialVersionModel(
        id=uuid4(),
        user_id=uuid4(),
        provider="deepseek",
        provider_name="tampered",
        base_url="https://attacker.example/v1",
        model="deepseek-reasoner",
        thinking_enabled=True,
        version=1,
        algorithm=LEGACY_ALGORITHM,
        nonce=bytes(12),
        ciphertext=b"x" * 17,
    )
    snapshot = service._configuration_snapshot(
        LinguaServiceStatus(
            enabled=True,
            available=True,
            version="0.3.2",
            pipeline_key="novel_txt_v1",
            pipeline_version="1",
            provider_id="openai-compatible",
            provider_name="Relay",
            provider_model="lingua-ingress-model",
            provider_offline=False,
            idempotency_required=True,
        ),
        credential,
    )
    assert snapshot["credential_provider"] == "openai_compatible"
    assert snapshot["credential_provider_name"] == "OpenAI"
    assert snapshot["credential_base_url"] == "https://operator-current.example/v1"
    assert snapshot["provider_model"] == "operator-current-model"
    assert snapshot["thinking_enabled"] is False


@pytest.mark.asyncio
async def test_new_openai_configuration_and_empty_status_ignore_legacy_upstream() -> None:
    service = object.__new__(ProviderCredentialService)
    service.settings = Settings(
        provider_relay_upstream_base_url="https://legacy-operator.example/v1",
        provider_relay_allowed_models=["legacy-ingress-model"],
    )
    empty_usage = UsageTotals(0, 0, 0, 0)
    current = AsyncMock(return_value=None)
    service.credentials = cast(
        Any,
        SimpleNamespace(
            current=current,
            latest=AsyncMock(return_value=None),
            all_time_and_current_month=AsyncMock(return_value=(empty_usage, empty_usage)),
        ),
    )

    configuration = service._provider_configuration(
        provider="openai_compatible",
        provider_name=None,
        base_url=None,
        model=None,
        thinking_enabled=False,
    )
    status = await service.status(uuid4())

    assert configuration.base_url == "https://api.openai.com/v1"
    assert configuration.model == "gpt-4.1-mini"
    assert status.configured is False
    assert status.base_url == "https://api.openai.com/v1"
    assert status.model == "gpt-4.1-mini"

    legacy = ProviderCredentialVersionModel(
        id=uuid4(),
        user_id=uuid4(),
        provider="openai_compatible",
        provider_name=None,
        base_url="https://migration-placeholder.invalid/v1",
        model="migration-placeholder",
        thinking_enabled=False,
        version=1,
        algorithm=LEGACY_ALGORITHM,
        nonce=bytes(12),
        ciphertext=b"x" * 17,
        created_at=datetime.now(UTC),
    )
    current.return_value = legacy
    legacy_status = await service.status(legacy.user_id)
    assert legacy_status.configured is True
    assert legacy_status.base_url == "https://legacy-operator.example/v1"
    assert legacy_status.model == "legacy-ingress-model"


@pytest.mark.parametrize(
    ("provider", "stored_name", "display_name"),
    [
        ("openai_compatible", None, "OpenAI"),
        ("deepseek", None, "DeepSeek"),
        ("kimi", None, "Kimi"),
        ("custom", "私有模型", "私有模型"),
    ],
)
def test_v2_run_snapshot_projects_non_empty_provider_display_name(
    provider: str,
    stored_name: str | None,
    display_name: str,
) -> None:
    service = object.__new__(TranslationRunService)
    service.settings = Settings()
    credential = ProviderCredentialVersionModel(
        id=uuid4(),
        user_id=uuid4(),
        provider=provider,
        provider_name=stored_name,
        base_url="https://provider.example/v1",
        model="translation-model",
        thinking_enabled=False,
        version=1,
        algorithm=ALGORITHM,
        nonce=bytes(12),
        ciphertext=b"x" * 17,
    )

    snapshot = service._configuration_snapshot(
        LinguaServiceStatus(
            enabled=True,
            available=True,
            version="0.3.2",
            pipeline_key="novel_txt_v1",
            pipeline_version="1",
            provider_id="openai-compatible",
            provider_name="Relay",
            provider_model="lingua-ingress-model",
            provider_offline=False,
            idempotency_required=True,
        ),
        credential,
    )

    assert snapshot["credential_provider"] == provider
    assert snapshot["credential_provider_name"] == display_name


def test_orm_custom_provider_constraint_requires_non_null_name() -> None:
    table = cast(Table, ProviderCredentialVersionModel.__table__)
    constraint = next(
        item
        for item in table.constraints
        if isinstance(item, CheckConstraint)
        and item.name == "ck_provider_credential_versions_provider_name_matches_provider"
    )

    assert "provider_name IS NOT NULL" in str(constraint.sqltext)


def test_provider_payload_requires_custom_fields_and_rejects_them_for_presets() -> None:
    default = ProviderCredentialPut.model_validate({"api_key": "sk-default"})
    assert default.provider == "openai_compatible"
    assert default.model is None
    assert default.thinking_enabled is False

    custom = ProviderCredentialPut.model_validate(
        {
            "provider": "custom",
            "custom_name": " 私有模型 ",
            "base_url": "https://provider.example/v1/",
            "model": " model-v1 ",
            "api_key": "sk-custom",
        }
    )
    assert custom.custom_name == "私有模型"
    assert custom.model == "model-v1"

    with pytest.raises(ValidationError, match="requires custom_name"):
        ProviderCredentialPut.model_validate(
            {
                "provider": "custom",
                "custom_name": "私有模型",
                "base_url": "https://provider.example/v1",
                "api_key": "sk-custom",
            }
        )
    with pytest.raises(ValidationError, match="do not accept"):
        ProviderCredentialPut.model_validate(
            {
                "provider": "deepseek",
                "base_url": "https://attacker.example/v1",
                "api_key": "sk-deepseek",
            }
        )


def test_custom_provider_base_url_allowlist_is_normalized_and_https_in_staging() -> None:
    settings = ProviderRelaySettings(
        provider_relay_custom_allowed_base_urls=["https://provider.example/v1/"],
    )
    assert settings.provider_relay_custom_allowed_base_urls == ["https://provider.example/v1"]

    with pytest.raises(ValidationError, match="must use HTTPS"):
        ProviderRelaySettings(
            environment="staging",
            provider_credential_master_key=SecretStr(base64.b64encode(bytes(range(32))).decode()),
            provider_relay_service_secret=SecretStr("relay-secret-" + ("r" * 32)),
            provider_relay_custom_allowed_base_urls=["http://provider.example/v1"],
        )


def test_v2_relay_destination_rechecks_bound_provider_policy() -> None:
    legacy_settings = ProviderRelaySettings(
        provider_relay_upstream_base_url="https://legacy-operator.example/v1"
    )
    openai = ProviderCredentialVersionModel(
        id=uuid4(),
        user_id=uuid4(),
        provider="openai_compatible",
        provider_name=None,
        base_url="https://api.openai.com/v1",
        model="gpt-4.1-mini",
        thinking_enabled=False,
        version=1,
        algorithm=ALGORITHM,
        nonce=bytes(12),
        ciphertext=b"x" * 17,
    )
    assert _bound_provider_destination(
        openai,
        "legacy-ingress-model",
        legacy_settings,
    ) == ("https://api.openai.com/v1", "gpt-4.1-mini")
    openai.base_url = "https://legacy-operator.example/v1"
    assert _bound_provider_destination(openai, "legacy-ingress-model", legacy_settings) is None

    stored = ProviderCredentialVersionModel(
        id=uuid4(),
        user_id=uuid4(),
        provider="custom",
        provider_name="私有模型",
        base_url="https://provider.example/v1",
        model="custom-model",
        thinking_enabled=False,
        version=1,
        algorithm=ALGORITHM,
        nonce=bytes(12),
        ciphertext=b"x" * 17,
    )
    allowed = ProviderRelaySettings(
        provider_relay_custom_allowed_base_urls=["https://provider.example/v1"],
    )
    denied = ProviderRelaySettings()
    assert _bound_provider_destination(stored, "lingua-ingress-model", allowed) == (
        "https://provider.example/v1",
        "custom-model",
    )
    assert _bound_provider_destination(stored, "lingua-ingress-model", denied) is None

    stored.provider = "deepseek"
    stored.provider_name = None
    stored.base_url = "https://api.deepseek.com/v1"
    stored.model = "deepseek-reasoner"
    stored.thinking_enabled = False
    assert _bound_provider_destination(stored, "lingua-ingress-model", denied) is None
    stored.thinking_enabled = True
    assert _bound_provider_destination(
        stored,
        "lingua-ingress-model",
        denied,
    ) == ("https://api.deepseek.com/v1", "deepseek-reasoner")


def test_thinking_configuration_fails_closed_for_unsupported_provider_model_pairs() -> None:
    ProviderCredentialService._validate_thinking_configuration(
        provider="deepseek",
        model="deepseek-reasoner",
        thinking_enabled=True,
    )
    ProviderCredentialService._validate_thinking_configuration(
        provider="kimi",
        model="kimi-k2.5",
        thinking_enabled=True,
    )
    with pytest.raises(ApplicationError, match="思考模式") as openai:
        ProviderCredentialService._validate_thinking_configuration(
            provider="openai_compatible",
            model="gpt-4.1-mini",
            thinking_enabled=True,
        )
    assert openai.value.code == "provider_thinking_not_supported"
    with pytest.raises(ApplicationError, match="思考模式") as custom:
        ProviderCredentialService._validate_thinking_configuration(
            provider="custom",
            model="custom-model",
            thinking_enabled=True,
        )
    assert custom.value.code == "provider_thinking_not_supported"
    with pytest.raises(ApplicationError, match="deepseek-reasoner") as deepseek:
        ProviderCredentialService._validate_thinking_configuration(
            provider="deepseek",
            model="deepseek-reasoner",
            thinking_enabled=False,
        )
    assert deepseek.value.code == "invalid_provider_thinking_configuration"
    with pytest.raises(ApplicationError, match=r"kimi-k2\.5") as kimi:
        ProviderCredentialService._validate_thinking_configuration(
            provider="kimi",
            model="moonshot-v1-8k",
            thinking_enabled=True,
        )
    assert kimi.value.code == "provider_thinking_not_supported"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("thinking_enabled", "expected_type"),
    [(False, "disabled"), (True, "enabled")],
)
async def test_kimi_relay_injects_explicit_bound_thinking_mode(
    thinking_enabled: bool,
    expected_type: str,
) -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(
            200,
            headers={"Content-Type": "application/json"},
            json={
                "model": "kimi-k2.5",
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": "Translated.",
                        }
                    }
                ],
            },
        )

    result = await _call_upstream(
        ChatCompletionRequest.model_validate(
            {
                "model": "lingua-ingress-model",
                "messages": [{"role": "user", "content": "正文"}],
            }
        ),
        "sk-kimi",
        ProviderRelaySettings(),
        base_url="https://api.moonshot.cn/v1",
        model="kimi-k2.5",
        provider="kimi",
        thinking_enabled=thinking_enabled,
        transport=httpx.MockTransport(handler),
    )
    assert isinstance(result, tuple)
    assert captured["model"] == "kimi-k2.5"
    assert captured["thinking"] == {"type": expected_type}


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
    for forbidden_field in ("thinking", "reasoning_effort"):
        with pytest.raises(ValidationError):
            ChatCompletionRequest.model_validate(
                {
                    "model": "gpt-4.1-mini",
                    "messages": [{"role": "user", "content": "正文"}],
                    forbidden_field: {"type": "enabled"},
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
