from uuid import UUID

from fastapi import APIRouter, status

from novel_platform.api.dependencies.auth import CurrentAuth
from novel_platform.api.dependencies.database import DatabaseSession
from novel_platform.api.dependencies.storage import FileStorageDependency
from novel_platform.api.dependencies.translation import (
    LinguaSpindleDependency,
    TranslationSettings,
)
from novel_platform.api.schemas import (
    TranslationRunCreate,
    TranslationRunResponse,
    TranslationServiceStatusResponse,
)
from novel_platform.api.translation_responses import (
    translation_run_responses,
    translation_service_response,
)
from novel_platform.application.access import LibraryAccessScope, LibraryAccessService
from novel_platform.application.translations.commands import CreateTranslationRun
from novel_platform.application.translations.service import TranslationRunService
from novel_platform.infrastructure.database.models import EditionTranslationRunModel

router = APIRouter(tags=["translations"])


async def _scope(session: DatabaseSession, auth: CurrentAuth) -> LibraryAccessScope:
    return await LibraryAccessService(session).require_translation(auth)


def _service(
    session: DatabaseSession,
    storage: FileStorageDependency,
    settings: TranslationSettings,
    client: LinguaSpindleDependency,
) -> TranslationRunService:
    return TranslationRunService(session, storage, settings, client)


async def _response(
    session: DatabaseSession,
    scope: LibraryAccessScope,
    run: EditionTranslationRunModel,
) -> TranslationRunResponse:
    responses = await translation_run_responses(session, scope, [run])
    return responses[0]


@router.get(
    "/translation-service/status",
    response_model=TranslationServiceStatusResponse,
)
async def get_translation_service_status(
    session: DatabaseSession,
    auth: CurrentAuth,
    storage: FileStorageDependency,
    settings: TranslationSettings,
    client: LinguaSpindleDependency,
) -> TranslationServiceStatusResponse:
    scope = await _scope(session, auth)
    service_status = await _service(session, storage, settings, client).service_status(scope)
    return translation_service_response(service_status)


@router.post(
    "/books/{book_id}/editions/{source_edition_id}/translation-runs",
    response_model=TranslationRunResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_translation_run(
    book_id: UUID,
    source_edition_id: UUID,
    payload: TranslationRunCreate,
    session: DatabaseSession,
    auth: CurrentAuth,
    storage: FileStorageDependency,
    settings: TranslationSettings,
    client: LinguaSpindleDependency,
) -> TranslationRunResponse:
    scope = await _scope(session, auth)
    run = await _service(session, storage, settings, client).create(
        scope=scope,
        book_id=book_id,
        source_edition_id=source_edition_id,
        command=CreateTranslationRun(
            target_language=payload.target_language,
            edition_title=payload.edition_title,
            client_request_id=payload.client_request_id,
            supersedes_edition_id=payload.supersedes_edition_id,
        ),
    )
    return await _response(session, scope, run)


@router.get("/translation-runs", response_model=list[TranslationRunResponse])
async def list_translation_runs(
    session: DatabaseSession,
    auth: CurrentAuth,
    storage: FileStorageDependency,
    settings: TranslationSettings,
    client: LinguaSpindleDependency,
    book_id: UUID | None = None,
) -> list[TranslationRunResponse]:
    scope = await _scope(session, auth)
    runs = await _service(session, storage, settings, client).list(scope, book_id=book_id)
    return await translation_run_responses(session, scope, runs)


@router.get("/translation-runs/{run_id}", response_model=TranslationRunResponse)
async def get_translation_run(
    run_id: UUID,
    session: DatabaseSession,
    auth: CurrentAuth,
    storage: FileStorageDependency,
    settings: TranslationSettings,
    client: LinguaSpindleDependency,
) -> TranslationRunResponse:
    scope = await _scope(session, auth)
    run = await _service(session, storage, settings, client).get(scope, run_id)
    return await _response(session, scope, run)


@router.post("/translation-runs/{run_id}/sync", response_model=TranslationRunResponse)
async def sync_translation_run(
    run_id: UUID,
    session: DatabaseSession,
    auth: CurrentAuth,
    storage: FileStorageDependency,
    settings: TranslationSettings,
    client: LinguaSpindleDependency,
) -> TranslationRunResponse:
    scope = await _scope(session, auth)
    run = await _service(session, storage, settings, client).sync(scope, run_id)
    return await _response(session, scope, run)


async def _control(
    action: str,
    run_id: UUID,
    session: DatabaseSession,
    auth: CurrentAuth,
    storage: FileStorageDependency,
    settings: TranslationSettings,
    client: LinguaSpindleDependency,
) -> TranslationRunResponse:
    scope = await _scope(session, auth)
    run = await _service(session, storage, settings, client).control(scope, run_id, action)
    return await _response(session, scope, run)


@router.post("/translation-runs/{run_id}/pause", response_model=TranslationRunResponse)
async def pause_translation_run(
    run_id: UUID,
    session: DatabaseSession,
    auth: CurrentAuth,
    storage: FileStorageDependency,
    settings: TranslationSettings,
    client: LinguaSpindleDependency,
) -> TranslationRunResponse:
    return await _control("pause", run_id, session, auth, storage, settings, client)


@router.post("/translation-runs/{run_id}/resume", response_model=TranslationRunResponse)
async def resume_translation_run(
    run_id: UUID,
    session: DatabaseSession,
    auth: CurrentAuth,
    storage: FileStorageDependency,
    settings: TranslationSettings,
    client: LinguaSpindleDependency,
) -> TranslationRunResponse:
    return await _control("resume", run_id, session, auth, storage, settings, client)


@router.post("/translation-runs/{run_id}/cancel", response_model=TranslationRunResponse)
async def cancel_translation_run(
    run_id: UUID,
    session: DatabaseSession,
    auth: CurrentAuth,
    storage: FileStorageDependency,
    settings: TranslationSettings,
    client: LinguaSpindleDependency,
) -> TranslationRunResponse:
    return await _control("cancel", run_id, session, auth, storage, settings, client)


@router.post("/translation-runs/{run_id}/retry", response_model=TranslationRunResponse)
async def retry_translation_run(
    run_id: UUID,
    session: DatabaseSession,
    auth: CurrentAuth,
    storage: FileStorageDependency,
    settings: TranslationSettings,
    client: LinguaSpindleDependency,
) -> TranslationRunResponse:
    return await _control("retry", run_id, session, auth, storage, settings, client)


@router.post("/translation-runs/{run_id}/cleanup", response_model=TranslationRunResponse)
async def cleanup_translation_run(
    run_id: UUID,
    session: DatabaseSession,
    auth: CurrentAuth,
    storage: FileStorageDependency,
    settings: TranslationSettings,
    client: LinguaSpindleDependency,
) -> TranslationRunResponse:
    scope = await _scope(session, auth)
    run = await _service(session, storage, settings, client).cleanup(scope, run_id)
    return await _response(session, scope, run)
