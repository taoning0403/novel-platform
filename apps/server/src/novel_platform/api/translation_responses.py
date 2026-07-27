from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from novel_platform.api.schemas import (
    ContributorSummary,
    TranslationRunResponse,
    TranslationServiceStatusResponse,
)
from novel_platform.application.access import LibraryAccessScope
from novel_platform.application.errors import ApplicationError
from novel_platform.domain.editions.models import EditionStatus
from novel_platform.domain.translations.models import (
    TERMINAL_TRANSLATION_RUN_STATUSES,
    TranslationCleanupStatus,
    TranslationRunStatus,
)
from novel_platform.infrastructure.database.models import (
    BookEditionModel,
    BookModel,
    EditionTranslationRunModel,
)
from novel_platform.infrastructure.integrations.linguaspindle import LinguaServiceStatus
from novel_platform.infrastructure.repositories.users import UserRepository

type TranslationAction = Literal["pause", "resume", "cancel", "retry", "sync", "cleanup"]


def translation_service_response(
    status: LinguaServiceStatus,
) -> TranslationServiceStatusResponse:
    return TranslationServiceStatusResponse(
        enabled=status.enabled,
        available=status.available,
        version=status.version,
        source_format=status.source_format,
        pipeline_key=status.pipeline_key,
        pipeline_version=status.pipeline_version,
        provider_id=status.provider_id,
        provider_name=status.provider_name,
        provider_model=status.provider_model,
        provider_offline=status.provider_offline,
        idempotency_required=status.idempotency_required,
        error_code=status.error_code,
        error_message=status.error_message,
    )


async def translation_run_responses(
    session: AsyncSession,
    scope: LibraryAccessScope,
    runs: list[EditionTranslationRunModel],
) -> list[TranslationRunResponse]:
    if not runs:
        return []
    book_ids = {run.book_id for run in runs}
    edition_ids = {
        edition_id
        for run in runs
        for edition_id in (
            run.source_edition_id,
            run.generated_edition_id,
        )
        if edition_id is not None
    }
    books = {
        book.id: book
        for book in (
            await session.scalars(select(BookModel).where(BookModel.id.in_(book_ids)))
        ).all()
    }
    editions = {
        edition.id: edition
        for edition in (
            await session.scalars(
                select(BookEditionModel).where(BookEditionModel.id.in_(edition_ids))
            )
        ).all()
    }
    names = await UserRepository(session).display_names({run.created_by_user_id for run in runs})
    responses: list[TranslationRunResponse] = []
    for run in runs:
        book = books.get(run.book_id)
        source = editions.get(run.source_edition_id)
        if book is None or source is None:
            raise ApplicationError(
                "translation_run_integrity_error",
                "翻译任务的馆藏关联不完整。",
                status_code=409,
            )
        generated = (
            editions.get(run.generated_edition_id) if run.generated_edition_id is not None else None
        )
        responses.append(
            TranslationRunResponse(
                id=run.id,
                book_id=run.book_id,
                book_title=book.canonical_title,
                source_edition_id=run.source_edition_id,
                source_edition_title=source.title,
                source_revision=run.source_revision,
                source_sha256=run.source_sha256,
                source_format=run.source_format,
                target_language=run.target_language,
                edition_title=run.edition_title,
                supersedes_edition_id=run.supersedes_edition_id,
                configuration=dict(run.configuration_snapshot),
                creator=ContributorSummary(
                    display_name=names.get(run.created_by_user_id, "已停用贡献者")
                ),
                status=run.status,
                progress=run.progress,
                generated_edition_id=run.generated_edition_id,
                generated_edition_title=generated.title if generated is not None else None,
                remote_project_id=run.remote_project_id,
                remote_job_id=run.remote_job_id,
                remote_artifact_id=run.remote_artifact_id,
                remote_request_id=run.remote_request_id,
                remote_status=run.remote_status,
                error_code=run.error_code,
                error_message=run.error_message,
                error_details=dict(run.error_details),
                retry_count=run.retry_count,
                cleanup_status=run.cleanup_status,
                cleanup_error=run.cleanup_error,
                available_actions=_available_actions(run),
                can_preview_draft=(
                    generated is not None and generated.status is EditionStatus.DRAFT
                ),
                can_publish=(
                    scope.can_manage
                    and generated is not None
                    and generated.status is EditionStatus.DRAFT
                ),
                created_at=run.created_at,
                updated_at=run.updated_at,
                started_at=run.started_at,
                completed_at=run.completed_at,
                last_synced_at=run.last_synced_at,
            )
        )
    return responses


def _available_actions(
    run: EditionTranslationRunModel,
) -> list[TranslationAction]:
    actions: list[TranslationAction] = []
    if run.status in {TranslationRunStatus.QUEUED, TranslationRunStatus.RUNNING}:
        actions.append("pause")
    if run.status is TranslationRunStatus.PAUSED:
        actions.append("resume")
    if run.status in {
        TranslationRunStatus.PREPARING,
        TranslationRunStatus.QUEUED,
        TranslationRunStatus.RUNNING,
        TranslationRunStatus.PAUSED,
        TranslationRunStatus.CANCELLING,
        TranslationRunStatus.ATTENTION_REQUIRED,
    }:
        actions.append("cancel")
    if run.status in {
        TranslationRunStatus.FAILED,
        TranslationRunStatus.PARTIALLY_SUCCEEDED,
    }:
        actions.append("retry")
    if run.status is not TranslationRunStatus.SUCCEEDED and run.remote_job_id is not None:
        actions.append("sync")
    if (
        run.status in TERMINAL_TRANSLATION_RUN_STATUSES
        and run.remote_project_id is not None
        and run.cleanup_status is not TranslationCleanupStatus.SUCCEEDED
    ):
        actions.append("cleanup")
    return actions
