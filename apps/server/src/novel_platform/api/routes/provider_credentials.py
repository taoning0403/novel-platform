from typing import Annotated

from fastapi import APIRouter, Depends, Response, status

from novel_platform.api.dependencies.auth import CurrentAuth
from novel_platform.api.dependencies.database import DatabaseSession
from novel_platform.api.schemas import (
    ProviderCredentialPut,
    ProviderCredentialStatusResponse,
    ProviderCredentialUsageResponse,
    ProviderUsageTotalsResponse,
)
from novel_platform.application.access import LibraryAccessService
from novel_platform.application.provider_credentials.service import (
    ProviderCredentialService,
    ProviderCredentialStatus,
)
from novel_platform.config import Settings, get_settings
from novel_platform.infrastructure.repositories.provider_credentials import UsageTotals

router = APIRouter(prefix="/me", tags=["provider-credentials"])
ProviderSettings = Annotated[Settings, Depends(get_settings)]


async def _require_translation(session: DatabaseSession, auth: CurrentAuth) -> None:
    await LibraryAccessService(session).require_translation(auth)


def _usage_totals(totals: UsageTotals) -> ProviderUsageTotalsResponse:
    return ProviderUsageTotalsResponse(
        request_count=totals.request_count,
        prompt_tokens=totals.prompt_tokens,
        completion_tokens=totals.completion_tokens,
        total_tokens=totals.total_tokens,
    )


def _usage_response(status_value: ProviderCredentialStatus) -> ProviderCredentialUsageResponse:
    return ProviderCredentialUsageResponse(
        all_time=_usage_totals(status_value.all_time),
        current_month=_usage_totals(status_value.current_month),
    )


def _status_response(
    status_value: ProviderCredentialStatus,
) -> ProviderCredentialStatusResponse:
    return ProviderCredentialStatusResponse(
        configured=status_value.configured,
        provider=status_value.provider,
        provider_name=status_value.provider_name,
        base_url=status_value.base_url,
        model=status_value.model,
        thinking_enabled=status_value.thinking_enabled,
        version=status_value.version,
        updated_at=status_value.updated_at,
        usage=_usage_response(status_value),
    )


@router.get(
    "/provider-credential",
    response_model=ProviderCredentialStatusResponse,
)
async def get_provider_credential(
    session: DatabaseSession,
    auth: CurrentAuth,
    settings: ProviderSettings,
) -> ProviderCredentialStatusResponse:
    await _require_translation(session, auth)
    return _status_response(await ProviderCredentialService(session, settings).status(auth.user.id))


@router.put(
    "/provider-credential",
    response_model=ProviderCredentialStatusResponse,
)
async def put_provider_credential(
    payload: ProviderCredentialPut,
    session: DatabaseSession,
    auth: CurrentAuth,
    settings: ProviderSettings,
) -> ProviderCredentialStatusResponse:
    await _require_translation(session, auth)
    return _status_response(
        await ProviderCredentialService(session, settings).rotate(
            auth,
            payload.api_key.get_secret_value(),
            provider=payload.provider,
            provider_name=payload.custom_name,
            base_url=payload.base_url,
            model=payload.model,
            thinking_enabled=payload.thinking_enabled,
        )
    )


@router.get(
    "/provider-credential/usage",
    response_model=ProviderCredentialUsageResponse,
)
async def get_provider_credential_usage(
    session: DatabaseSession,
    auth: CurrentAuth,
    settings: ProviderSettings,
) -> ProviderCredentialUsageResponse:
    await _require_translation(session, auth)
    status_value = await ProviderCredentialService(session, settings).status(auth.user.id)
    return _usage_response(status_value)


@router.delete(
    "/provider-credential",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_provider_credential(
    session: DatabaseSession,
    auth: CurrentAuth,
    settings: ProviderSettings,
) -> Response:
    await _require_translation(session, auth)
    await ProviderCredentialService(session, settings).remove(auth)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
