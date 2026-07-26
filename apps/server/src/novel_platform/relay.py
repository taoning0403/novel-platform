import json
import logging
import re
import secrets
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Annotated, Any, Literal
from uuid import UUID

import httpx
from fastapi import Depends, FastAPI, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from novel_platform.application.provider_credentials.service import (
    ALGORITHM,
    CUSTOM_PROVIDER,
    DEEPSEEK_BASE_URL,
    DEEPSEEK_PROVIDER,
    KIMI_BASE_URL,
    KIMI_PROVIDER,
    KIMI_THINKING_MODEL,
    LEGACY_ALGORITHM,
    OPENAI_BASE_URL,
    OPENAI_COMPATIBLE_PROVIDER,
    ProviderCredentialCipher,
    ProviderCredentialConfigurationError,
    ProviderCredentialDecryptionError,
)
from novel_platform.config import ProviderRelaySettings, get_provider_relay_settings
from novel_platform.infrastructure.database.models import ProviderCredentialVersionModel
from novel_platform.infrastructure.integrations.provider_http import (
    bounded_response_body,
    contains_secret,
)
from novel_platform.infrastructure.repositories.provider_credentials import (
    ProviderCredentialRepository,
)

logger = logging.getLogger("novel_platform.provider_relay")
settings = get_provider_relay_settings()
logging.basicConfig(level=settings.log_level.upper())
engine = create_async_engine(settings.database_url, pool_pre_ping=True)
session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

app = FastAPI(
    title="Novel Platform Provider Relay",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)
app.state.upstream_transport = None


@app.middleware("http")
async def suppress_unhandled_exception_details(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    try:
        return await call_next(request)
    except Exception as exc:
        logger.error(
            "Provider relay request failed unexpectedly (%s)",
            type(exc).__name__,
        )
        return _error(503, "provider_relay_unavailable")


async def get_relay_session() -> AsyncIterator[AsyncSession]:
    async with session_factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


DatabaseSession = Annotated[AsyncSession, Depends(get_relay_session)]
_SAFE_REMOTE_ID = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
_JSON_CONTENT_TYPES = {"application/json"}


class RelayModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class ChatMessage(RelayModel):
    role: Literal["system", "user", "assistant"]
    content: str = Field(min_length=1, max_length=1_000_000)


class ChatCompletionRequest(RelayModel):
    model: str = Field(min_length=1, max_length=120)
    messages: list[ChatMessage] = Field(min_length=1, max_length=128)
    stream: Literal[False] = False
    temperature: float | None = Field(default=None, ge=0, le=2)
    top_p: float | None = Field(default=None, gt=0, le=1)
    max_tokens: int | None = Field(default=None, ge=1, le=1_000_000)
    max_completion_tokens: int | None = Field(default=None, ge=1, le=1_000_000)
    seed: int | None = Field(default=None, ge=-(2**63), le=2**63 - 1)
    frequency_penalty: float | None = Field(default=None, ge=-2, le=2)
    presence_penalty: float | None = Field(default=None, ge=-2, le=2)
    stop: str | list[str] | None = None

    @field_validator("model")
    @classmethod
    def validate_model(cls, value: str) -> str:
        if value != value.strip() or not value.isprintable():
            raise ValueError("invalid model")
        return value

    @field_validator("stop")
    @classmethod
    def validate_stop(cls, value: str | list[str] | None) -> str | list[str] | None:
        values = [value] if isinstance(value, str) else value
        if values is not None and (
            not values or len(values) > 4 or any(not item or len(item) > 1000 for item in values)
        ):
            raise ValueError("invalid stop sequences")
        return value


@app.get("/health")
async def health(session: DatabaseSession) -> JSONResponse:
    try:
        ProviderCredentialCipher(settings)
        if settings.provider_relay_service_secret is None:
            raise ProviderCredentialConfigurationError("relay secret missing")
        await session.execute(text("SELECT 1"))
    except Exception:
        return JSONResponse(status_code=503, content={"status": "unavailable"})
    return JSONResponse(content={"status": "ok"})


@app.post("/v1/chat/completions")
async def chat_completions(
    request: Request,
    session: DatabaseSession,
) -> JSONResponse:
    if not _authorized(request, settings):
        return _error(
            401,
            "relay_authentication_required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    credential_scope = _single_header(
        request,
        "X-LinguaSpindle-Credential-Scope",
    )
    scope_id = _canonical_uuid(credential_scope)
    if scope_id is None:
        return _error(404, "provider_credential_unavailable")

    remote_job_id = _single_header(request, "X-LinguaSpindle-Job-ID")
    if remote_job_id is None or _SAFE_REMOTE_ID.fullmatch(remote_job_id) is None:
        return _error(400, "invalid_job_correlation")

    content_type = request.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
    if content_type not in _JSON_CONTENT_TYPES:
        return _error(415, "json_request_required")
    body = await _bounded_request_body(request, settings.provider_relay_max_request_bytes)
    if body is None:
        return _error(413, "provider_request_too_large")
    try:
        raw_payload = json.loads(body)
        payload = ChatCompletionRequest.model_validate(raw_payload)
    except (UnicodeDecodeError, json.JSONDecodeError, ValidationError):
        return _error(422, "invalid_chat_completion_request")
    if payload.model not in settings.provider_relay_allowed_models:
        return _error(403, "provider_model_not_allowed")

    credentials = ProviderCredentialRepository(session)
    credential = await credentials.resolve_for_relay(
        scope_id,
        remote_job_id=remote_job_id,
    )
    if credential is None:
        return _error(404, "provider_credential_unavailable")
    destination = _bound_provider_destination(credential, payload.model, settings)
    if destination is None:
        await session.rollback()
        return _error(503, "provider_configuration_unavailable")
    effective_base_url, effective_model = destination
    # Persist and release the short bootstrap lock before the potentially slow
    # upstream call. A first scoped Provider request may race Novel Platform
    # persisting the Job-creation response; subsequent calls must match the
    # atomically claimed Job ID.
    await session.commit()
    try:
        api_key = ProviderCredentialCipher(settings).decrypt(credential)
    except (ProviderCredentialConfigurationError, ProviderCredentialDecryptionError):
        return _error(503, "provider_credential_store_unavailable")

    upstream = await _call_upstream(
        payload,
        api_key,
        settings,
        base_url=effective_base_url,
        model=effective_model,
        provider=(credential.provider if credential.algorithm != LEGACY_ALGORITHM else None),
        thinking_enabled=(
            credential.thinking_enabled if credential.algorithm != LEGACY_ALGORITHM else False
        ),
        transport=request.app.state.upstream_transport,
    )
    if isinstance(upstream, JSONResponse):
        return upstream
    sanitized, usage = upstream
    if usage is not None:
        try:
            await credentials.add_usage(
                credential=credential,
                model=effective_model,
                prompt_tokens=usage["prompt_tokens"],
                completion_tokens=usage["completion_tokens"],
                total_tokens=usage["total_tokens"],
                remote_job_id=remote_job_id,
            )
            await session.commit()
        except Exception:
            await session.rollback()
            logger.warning("Provider usage persistence failed")
    return JSONResponse(content=sanitized)


async def _call_upstream(
    payload: ChatCompletionRequest,
    api_key: str,
    relay_settings: ProviderRelaySettings,
    *,
    base_url: str | None = None,
    model: str | None = None,
    provider: str | None = None,
    thinking_enabled: bool = False,
    transport: httpx.AsyncBaseTransport | None = None,
) -> tuple[dict[str, Any], dict[str, int] | None] | JSONResponse:
    upstream_base_url = base_url or relay_settings.provider_relay_upstream_base_url
    upstream_model = model or payload.model
    outbound_payload = payload.model_dump(exclude_none=True)
    outbound_payload["model"] = upstream_model
    if provider == KIMI_PROVIDER and upstream_model == KIMI_THINKING_MODEL:
        outbound_payload["thinking"] = {"type": "enabled" if thinking_enabled else "disabled"}
    timeout = httpx.Timeout(
        connect=relay_settings.provider_relay_connect_timeout_seconds,
        read=relay_settings.provider_relay_read_timeout_seconds,
        write=relay_settings.provider_relay_read_timeout_seconds,
        pool=relay_settings.provider_relay_connect_timeout_seconds,
    )
    try:
        async with httpx.AsyncClient(
            base_url=f"{upstream_base_url}/",
            timeout=timeout,
            follow_redirects=False,
            trust_env=False,
            transport=transport,
        ) as client:
            async with client.stream(
                "POST",
                "chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                },
                json=outbound_payload,
            ) as response:
                if 300 <= response.status_code < 400:
                    return _error(502, "provider_protocol_error")
                response_body = await bounded_response_body(
                    response,
                    relay_settings.provider_relay_max_response_bytes,
                )
                if response_body is None:
                    return _error(502, "provider_response_too_large")
                if response.status_code >= 400:
                    return _upstream_error(response.status_code)
                response_type = (
                    response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
                )
                if response_type not in _JSON_CONTENT_TYPES:
                    return _error(502, "provider_protocol_error")
    except httpx.DecodingError:
        return _error(502, "provider_protocol_error")
    except (httpx.TimeoutException, httpx.TransportError):
        return _error(503, "provider_unavailable")

    try:
        raw_response = json.loads(response_body)
        return _sanitize_upstream_response(
            raw_response,
            requested_model=upstream_model,
            forbidden_secret=api_key,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
        return _error(502, "provider_protocol_error")


def _sanitize_upstream_response(
    payload: object,
    *,
    requested_model: str,
    forbidden_secret: str,
) -> tuple[dict[str, Any], dict[str, int] | None]:
    if contains_secret(payload, forbidden_secret):
        raise ValueError("response contains forbidden secret")
    if not isinstance(payload, dict):
        raise ValueError("response must be an object")
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        raise ValueError("response must contain a choice")
    message = choices[0].get("message")
    if not isinstance(message, dict):
        raise ValueError("response choice must contain a message")
    content = message.get("content")
    if not isinstance(content, str) or not content.strip():
        raise ValueError("response message must contain text")
    upstream_model = payload.get("model")
    model = (
        upstream_model
        if isinstance(upstream_model, str)
        and 0 < len(upstream_model) <= 120
        and upstream_model.isprintable()
        else requested_model
    )
    finish_reason = choices[0].get("finish_reason")
    if not isinstance(finish_reason, str) or len(finish_reason) > 50:
        finish_reason = None
    sanitized: dict[str, Any] = {
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": content,
                },
                "finish_reason": finish_reason,
            }
        ],
    }
    usage = _sanitize_usage(payload.get("usage"))
    if usage is not None:
        sanitized["usage"] = usage
    return sanitized, usage


def _sanitize_usage(value: object) -> dict[str, int] | None:
    if not isinstance(value, dict):
        return None
    names = ("prompt_tokens", "completion_tokens", "total_tokens")
    if any(
        not isinstance(value.get(name), int) or isinstance(value.get(name), bool) or value[name] < 0
        for name in names
    ):
        return None
    usage = {name: int(value[name]) for name in names}
    if (
        usage["total_tokens"] < usage["prompt_tokens"]
        or usage["total_tokens"] < usage["completion_tokens"]
    ):
        return None
    return usage


async def _bounded_request_body(request: Request, max_bytes: int) -> bytes | None:
    declared = request.headers.get("Content-Length")
    if declared is not None:
        try:
            if int(declared) < 0 or int(declared) > max_bytes:
                return None
        except ValueError:
            return None
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > max_bytes:
            return None
    return bytes(body)


def _authorized(request: Request, relay_settings: ProviderRelaySettings) -> bool:
    authorization = _single_header(request, "Authorization")
    configured = relay_settings.provider_relay_service_secret
    if authorization is None or configured is None:
        return False
    expected = f"Bearer {configured.get_secret_value()}"
    return secrets.compare_digest(authorization, expected)


def _bound_provider_destination(
    credential: ProviderCredentialVersionModel,
    inbound_model: str,
    relay_settings: ProviderRelaySettings,
) -> tuple[str, str] | None:
    if credential.algorithm == LEGACY_ALGORITHM:
        if credential.provider != OPENAI_COMPATIBLE_PROVIDER:
            return None
        return relay_settings.provider_relay_upstream_base_url, inbound_model
    if credential.algorithm != ALGORITHM:
        return None
    if (
        not isinstance(credential.model, str)
        or not credential.model
        or len(credential.model) > 120
        or credential.model != credential.model.strip()
        or not credential.model.isprintable()
        or not _thinking_configuration_allowed(credential)
    ):
        return None
    preset_base_urls = {
        OPENAI_COMPATIBLE_PROVIDER: OPENAI_BASE_URL,
        DEEPSEEK_PROVIDER: DEEPSEEK_BASE_URL,
        KIMI_PROVIDER: KIMI_BASE_URL,
    }
    if credential.provider in preset_base_urls:
        allowed = (
            credential.provider_name is None
            and credential.base_url == preset_base_urls[credential.provider]
        )
        return (credential.base_url, credential.model) if allowed else None
    if credential.provider == CUSTOM_PROVIDER:
        allowed = (
            isinstance(credential.provider_name, str)
            and bool(credential.provider_name.strip())
            and credential.provider_name == credential.provider_name.strip()
            and credential.base_url in relay_settings.provider_relay_custom_allowed_base_urls
        )
        return (credential.base_url, credential.model) if allowed else None
    return None


def _thinking_configuration_allowed(
    credential: ProviderCredentialVersionModel,
) -> bool:
    if credential.provider in {OPENAI_COMPATIBLE_PROVIDER, CUSTOM_PROVIDER}:
        return not credential.thinking_enabled
    if credential.provider == DEEPSEEK_PROVIDER:
        return credential.thinking_enabled == (credential.model == "deepseek-reasoner")
    if credential.provider == KIMI_PROVIDER:
        return not credential.thinking_enabled or credential.model == KIMI_THINKING_MODEL
    return False


def _single_header(
    request: Request,
    name: str,
) -> str | None:
    values = request.headers.getlist(name)
    if len(values) != 1:
        return None
    value = values[0]
    if not value or "\r" in value or "\n" in value:
        return None
    return value


def _canonical_uuid(value: str | None) -> UUID | None:
    if value is None:
        return None
    try:
        parsed = UUID(value)
    except ValueError:
        return None
    return parsed if str(parsed) == value else None


def _upstream_error(status_code: int) -> JSONResponse:
    if status_code == 429:
        return _error(429, "provider_rate_limited")
    if status_code >= 500:
        return _error(503, "provider_unavailable")
    return _error(502, "provider_request_rejected")


def _error(
    status_code: int,
    code: str,
    *,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        headers=headers,
        content={
            "error": {
                "code": code,
                "message": "Provider relay request failed.",
            }
        },
    )
