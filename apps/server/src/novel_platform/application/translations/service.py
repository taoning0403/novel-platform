import hashlib
import json
from datetime import UTC, datetime
from pathlib import PurePath
from typing import cast
from uuid import UUID

from anyio import to_thread
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from novel_platform.application.access import LibraryAccessScope
from novel_platform.application.errors import ApplicationError
from novel_platform.application.library.storage import FileStorage, StorageError
from novel_platform.application.provider_credentials.service import (
    CUSTOM_PROVIDER,
    LEGACY_ALGORITHM,
    OPENAI_COMPATIBLE_PROVIDER,
    PROVIDER_DISPLAY_NAMES,
    ProviderCredentialService,
    ProviderKind,
)
from novel_platform.application.translations.commands import CreateTranslationRun
from novel_platform.application.translations.ingestion_service import (
    GeneratedTranslationIngestionService,
)
from novel_platform.config import Settings
from novel_platform.domain.auth.capabilities import CredentialCapability
from novel_platform.domain.editions.models import (
    ContentRole,
    CreationMethod,
    EditionStatus,
)
from novel_platform.domain.library.models import FileFormat
from novel_platform.domain.translations.models import (
    TERMINAL_TRANSLATION_RUN_STATUSES,
    TranslationCleanupStatus,
    TranslationRunStatus,
    local_status_for_remote,
)
from novel_platform.infrastructure.database.models import (
    BookEditionModel,
    EditionTranslationRunModel,
    ProviderCredentialVersionModel,
)
from novel_platform.infrastructure.integrations.linguaspindle import (
    LinguaServiceStatus,
    LinguaSpindleFailure,
    LinguaSpindleGateway,
    RemoteJob,
    translation_format_contract,
)
from novel_platform.infrastructure.repositories.books import BookRepository
from novel_platform.infrastructure.repositories.editions import EditionRepository
from novel_platform.infrastructure.repositories.library import LibraryRepository
from novel_platform.infrastructure.repositories.translation_runs import TranslationRunRepository


class TranslationRunService:
    def __init__(
        self,
        session: AsyncSession,
        storage: FileStorage,
        settings: Settings,
        client: LinguaSpindleGateway,
    ) -> None:
        self.session = session
        self.storage = storage
        self.settings = settings
        self.client = client
        self.runs = TranslationRunRepository(session)
        self.books = BookRepository(session)
        self.editions = EditionRepository(session)
        self.library = LibraryRepository(session)
        self.provider_credentials = ProviderCredentialService(session, settings)
        self.ingestion = GeneratedTranslationIngestionService(session, storage, settings, client)

    async def service_status(
        self,
        scope: LibraryAccessScope,
        source_format: FileFormat,
    ) -> LinguaServiceStatus:
        self._require_translation(scope)
        try:
            translation_format_contract(source_format)
        except ValueError as exc:
            raise ApplicationError(
                "translation_source_format_unsupported",
                "小说翻译仅支持 EPUB 或 TXT 原文。",
                status_code=422,
            ) from exc
        return await self.client.service_status(
            source_format=source_format,
            request_id=f"np-status-{source_format.value}-v1",
        )

    async def create(
        self,
        *,
        scope: LibraryAccessScope,
        book_id: UUID,
        source_edition_id: UUID,
        command: CreateTranslationRun,
    ) -> EditionTranslationRunModel:
        self._require_translation(scope)
        existing = await self.runs.get_by_client_request(
            scope.owner_user_id,
            scope.viewer_user_id,
            command.client_request_id,
        )
        if existing is not None:
            self._require_same_request(existing, book_id, source_edition_id, command)
            return existing

        book = await self.books.get(book_id, scope.owner_user_id)
        source = await self.editions.get_readable(scope.owner_user_id, source_edition_id)
        if book is None or source is None or source.book_id != book_id:
            raise ApplicationError("edition_not_found", "可翻译的原文版本不存在。", status_code=404)
        if (
            source.content_role is not ContentRole.SOURCE
            or source.status is not EditionStatus.READY
        ):
            raise ApplicationError(
                "translation_source_required",
                "只能翻译已就绪的原文版本。",
                status_code=409,
            )
        source_file = await self.library.get_current_edition_file_for_owner(
            scope.owner_user_id, source.id
        )
        if source_file is None:
            raise ApplicationError(
                "translation_source_file_required",
                "原文版本没有可翻译的当前文件。",
                status_code=409,
            )
        source_format = source_file.stored_file.file_format
        try:
            translation_format_contract(source_format)
        except ValueError as exc:
            raise ApplicationError(
                "translation_source_format_unsupported",
                "小说翻译仅支持 EPUB 或 TXT 原文。",
                status_code=409,
            ) from exc
        if not await to_thread.run_sync(self.storage.exists, source_file.stored_file.storage_key):
            raise ApplicationError("source_file_unavailable", "原文文件不可用。", status_code=409)
        actual_sha256 = await to_thread.run_sync(
            self.storage.calculate_checksum, source_file.stored_file.storage_key
        )
        if actual_sha256 != source_file.stored_file.sha256:
            raise ApplicationError(
                "source_file_integrity_error", "原文文件完整性校验失败。", status_code=409
            )
        status = await self.client.service_status(
            source_format=source_format,
            request_id=f"np-create-{command.client_request_id}",
        )
        if not status.enabled:
            raise ApplicationError("feature_disabled", "小说翻译服务未启用。", status_code=503)
        if not status.available:
            raise ApplicationError(
                status.error_code or "translation_service_unavailable",
                status.error_message or "小说翻译服务暂不可用。",
                status_code=503,
            )
        provider_credential = await self.provider_credentials.current_for_run(scope.viewer_user_id)
        await self._validate_supersedes(scope, book_id, source.id, command.supersedes_edition_id)

        target_language = command.target_language.strip()
        edition_title = command.edition_title.strip()
        if not target_language or len(target_language) > 100:
            raise ApplicationError("invalid_target_language", "目标语言无效。", status_code=422)
        if not edition_title or len(edition_title) > 500:
            raise ApplicationError("invalid_edition_title", "译本标题无效。", status_code=422)
        configuration = self._configuration_snapshot(status, provider_credential)
        fingerprint = hashlib.sha256(
            json.dumps(
                {
                    **configuration,
                    "credential_scope": str(provider_credential.id),
                },
                ensure_ascii=True,
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        run = EditionTranslationRunModel(
            library_owner_user_id=scope.owner_user_id,
            created_by_user_id=scope.viewer_user_id,
            provider_credential_version_id=provider_credential.id,
            book_id=book_id,
            source_edition_id=source.id,
            source_edition_file_id=source_file.edition_file.id,
            source_revision=source_file.edition_file.revision,
            source_sha256=source_file.stored_file.sha256,
            source_format=source_format,
            target_language=target_language,
            edition_title=edition_title,
            supersedes_edition_id=command.supersedes_edition_id,
            configuration_fingerprint=fingerprint,
            configuration_snapshot=configuration,
            client_request_id=command.client_request_id,
            status=TranslationRunStatus.PREPARING,
            progress=0,
        )
        try:
            await self.runs.add(run)
            await self.session.commit()
        except IntegrityError as exc:
            await self.session.rollback()
            replay = await self.runs.get_by_client_request(
                scope.owner_user_id,
                scope.viewer_user_id,
                command.client_request_id,
            )
            if replay is not None:
                self._require_same_request(replay, book_id, source_edition_id, command)
                return replay
            raise ApplicationError(
                "translation_run_already_active",
                "相同原文、目标语言与配置已有活动翻译任务。",
                status_code=409,
            ) from exc
        return await self._ensure_remote(scope.owner_user_id, run.id)

    async def list(
        self,
        scope: LibraryAccessScope,
        *,
        book_id: UUID | None = None,
    ) -> list[EditionTranslationRunModel]:
        self._require_translation(scope)
        return await self.runs.list_visible(
            scope.owner_user_id,
            creator_user_id=None if scope.can_manage else scope.viewer_user_id,
            book_id=book_id,
        )

    async def get(self, scope: LibraryAccessScope, run_id: UUID) -> EditionTranslationRunModel:
        self._require_translation(scope)
        run = await self.runs.get(
            scope.owner_user_id,
            run_id,
            creator_user_id=None if scope.can_manage else scope.viewer_user_id,
        )
        if run is None:
            raise ApplicationError("translation_run_not_found", "翻译任务不存在。", status_code=404)
        return run

    async def sync(self, scope: LibraryAccessScope, run_id: UUID) -> EditionTranslationRunModel:
        run = await self.get(scope, run_id)
        if run.status is TranslationRunStatus.SUCCEEDED and run.generated_edition_id is not None:
            return run
        if run.status in {
            TranslationRunStatus.PREPARING,
            TranslationRunStatus.ATTENTION_REQUIRED,
        } and (run.remote_project_id is None or run.remote_job_id is None):
            if run.status is TranslationRunStatus.ATTENTION_REQUIRED:
                run = await self._resume_preparation(scope.owner_user_id, run_id)
            run = await self._ensure_remote(scope.owner_user_id, run_id)
            if run.remote_job_id is None:
                return run
        if run.remote_job_id is None:
            return run
        request_id = self._request_id(run_id)
        try:
            remote = await self.client.get_job(run.remote_job_id, request_id=request_id)
            if run.remote_project_id is not None and remote.project_id != run.remote_project_id:
                raise LinguaSpindleFailure(
                    "translation_protocol_error",
                    "小说翻译服务返回了不兼容的响应。",
                    status_code=502,
                )
            await self._apply_remote_status(scope.owner_user_id, run_id, remote)
            if remote.status != "succeeded":
                return await self._required_run(scope.owner_user_id, run_id)
            artifacts = await self.client.list_artifacts(
                remote.project_id,
                remote.id,
                request_id=request_id,
            )
            format_contract = translation_format_contract(run.source_format)
            outputs = [item for item in artifacts if item.kind == format_contract.artifact_kind]
            if len(outputs) != 1:
                raise LinguaSpindleFailure(
                    "translation_artifact_ambiguous",
                    f"翻译任务没有唯一完整的 {format_contract.label} 产物。",
                    status_code=502,
                )
            artifact = outputs[0]
            locked = await self.runs.get(scope.owner_user_id, run_id, for_update=True)
            if locked is None:
                raise self._not_found()
            if locked.generated_edition_id is not None:
                return locked
            locked.remote_artifact_id = artifact.id
            locked.status = TranslationRunStatus.INGESTING
            locked.updated_at = datetime.now(UTC)
            await self.session.commit()
            await self.ingestion.ingest(
                owner_user_id=scope.owner_user_id,
                run_id=run_id,
                artifact=artifact,
                request_id=request_id,
            )
            completed = await self._required_run(scope.owner_user_id, run_id)
            await self.cleanup(scope, run_id, suppress_failure=True)
            return await self._required_run(scope.owner_user_id, completed.id)
        except (LinguaSpindleFailure, ApplicationError) as exc:
            await self._record_failure(scope.owner_user_id, run_id, exc, phase="sync")
            return await self._required_run(scope.owner_user_id, run_id)

    async def control(
        self,
        scope: LibraryAccessScope,
        run_id: UUID,
        action: str,
    ) -> EditionTranslationRunModel:
        run = await self.get(scope, run_id)
        allowed: dict[str, set[TranslationRunStatus]] = {
            "pause": {TranslationRunStatus.QUEUED, TranslationRunStatus.RUNNING},
            "resume": {TranslationRunStatus.PAUSED},
            "cancel": {
                TranslationRunStatus.PREPARING,
                TranslationRunStatus.QUEUED,
                TranslationRunStatus.RUNNING,
                TranslationRunStatus.PAUSED,
                TranslationRunStatus.CANCELLING,
                TranslationRunStatus.ATTENTION_REQUIRED,
            },
            "retry": {
                TranslationRunStatus.FAILED,
                TranslationRunStatus.PARTIALLY_SUCCEEDED,
            },
        }
        if action not in allowed or run.status not in allowed[action]:
            raise ApplicationError(
                "translation_control_conflict",
                "翻译任务当前不能执行该操作。",
                status_code=409,
            )
        retry_previous_status: TranslationRunStatus | None = None
        retry_previous_completed_at: datetime | None = None
        if action == "retry":
            (
                run,
                retry_previous_status,
                retry_previous_completed_at,
            ) = await self._begin_retry(scope.owner_user_id, run_id)
        had_remote_job = run.remote_job_id is not None
        if run.remote_job_id is None:
            if action == "cancel" and run.remote_project_id is None:
                run.status = TranslationRunStatus.CANCELLED
                run.completed_at = datetime.now(UTC)
                run.updated_at = run.completed_at
                await self.session.commit()
                return run
            run = await self._ensure_remote(scope.owner_user_id, run_id)
        if run.remote_job_id is None:
            raise ApplicationError(
                "translation_remote_job_missing",
                "翻译任务尚未建立远端 Job。",
                status_code=409,
            )
        if (
            action == "retry"
            and not had_remote_job
            and run.status
            not in {
                TranslationRunStatus.FAILED,
                TranslationRunStatus.PARTIALLY_SUCCEEDED,
            }
        ):
            return run
        retry_count = run.retry_count + 1 if action == "retry" else run.retry_count
        idempotency_key = f"np:{run_id}:retry:{retry_count}:v1" if action == "retry" else None
        try:
            remote = await self.client.control_job(
                run.remote_job_id,
                action,
                request_id=self._request_id(run_id),
                idempotency_key=idempotency_key,
            )
            await self._apply_remote_status(
                scope.owner_user_id,
                run_id,
                remote,
                retry_count=retry_count if action == "retry" else None,
            )
        except LinguaSpindleFailure as exc:
            if exc.ambiguous:
                await self._record_failure(scope.owner_user_id, run_id, exc, phase=action)
            else:
                await self.session.rollback()
                current = await self.runs.get(scope.owner_user_id, run_id, for_update=True)
                if current is not None:
                    if action == "retry" and retry_previous_status is not None:
                        current.status = retry_previous_status
                        current.completed_at = retry_previous_completed_at
                    current.error_code = exc.code
                    current.error_message = exc.message
                    current.error_details = {
                        "phase": action,
                        "retryable": exc.retryable,
                    }
                    current.updated_at = datetime.now(UTC)
                    await self.session.commit()
                raise ApplicationError(
                    exc.code,
                    exc.message,
                    status_code=exc.status_code,
                ) from exc
        except IntegrityError as exc:
            await self.session.rollback()
            if action == "retry":
                current = await self.runs.get(scope.owner_user_id, run_id, for_update=True)
                if current is not None:
                    current.status = TranslationRunStatus.ATTENTION_REQUIRED
                    current.completed_at = None
                    current.error_code = "translation_retry_state_conflict"
                    current.error_message = "远端重试结果需要人工确认。"
                    current.error_details = {
                        "phase": action,
                        "retryable": True,
                    }
                    current.updated_at = datetime.now(UTC)
                    await self.session.commit()
            raise ApplicationError(
                "translation_run_already_active",
                "相同原文、目标语言与配置已有活动翻译任务。",
                status_code=409,
            ) from exc
        return await self._required_run(scope.owner_user_id, run_id)

    async def _begin_retry(
        self,
        owner_user_id: UUID,
        run_id: UUID,
    ) -> tuple[
        EditionTranslationRunModel,
        TranslationRunStatus,
        datetime | None,
    ]:
        run = await self.runs.get(owner_user_id, run_id, for_update=True)
        if run is None:
            raise self._not_found()
        if run.status not in {
            TranslationRunStatus.FAILED,
            TranslationRunStatus.PARTIALLY_SUCCEEDED,
        }:
            raise ApplicationError(
                "translation_control_conflict",
                "翻译任务当前不能执行该操作。",
                status_code=409,
            )
        previous_status = run.status
        previous_completed_at = run.completed_at
        run.status = TranslationRunStatus.PREPARING
        run.completed_at = None
        run.error_code = None
        run.error_message = None
        run.error_details = {}
        run.updated_at = datetime.now(UTC)
        try:
            await self.session.commit()
        except IntegrityError as exc:
            await self.session.rollback()
            raise ApplicationError(
                "translation_run_already_active",
                "相同原文、目标语言与配置已有活动翻译任务。",
                status_code=409,
            ) from exc
        return (
            await self._required_run(owner_user_id, run_id),
            previous_status,
            previous_completed_at,
        )

    async def _resume_preparation(
        self,
        owner_user_id: UUID,
        run_id: UUID,
    ) -> EditionTranslationRunModel:
        run = await self.runs.get(owner_user_id, run_id, for_update=True)
        if run is None:
            raise self._not_found()
        if run.status is TranslationRunStatus.ATTENTION_REQUIRED and (
            run.remote_project_id is None or run.remote_job_id is None
        ):
            run.status = TranslationRunStatus.PREPARING
            run.completed_at = None
            run.error_code = None
            run.error_message = None
            run.error_details = {}
            run.updated_at = datetime.now(UTC)
            try:
                await self.session.commit()
            except IntegrityError as exc:
                await self.session.rollback()
                raise ApplicationError(
                    "translation_preparation_busy",
                    "同一凭据已有任务正在建立远端关联，请稍后重试。",
                    status_code=409,
                ) from exc
        return await self._required_run(owner_user_id, run_id)

    async def cleanup(
        self,
        scope: LibraryAccessScope,
        run_id: UUID,
        *,
        suppress_failure: bool = False,
    ) -> EditionTranslationRunModel:
        run = await self.get(scope, run_id)
        if run.status not in TERMINAL_TRANSLATION_RUN_STATUSES:
            raise ApplicationError(
                "translation_cleanup_conflict",
                "只能清理已终止的翻译任务。",
                status_code=409,
            )
        if run.remote_project_id is None:
            run.cleanup_status = TranslationCleanupStatus.NOT_REQUIRED
            run.cleanup_error = None
            await self.session.commit()
            return run
        run.cleanup_status = TranslationCleanupStatus.PENDING
        run.cleanup_error = None
        run.updated_at = datetime.now(UTC)
        remote_project_id = run.remote_project_id
        await self.session.commit()
        try:
            await self.client.delete_project(
                remote_project_id,
                request_id=self._request_id(run_id),
            )
            run = await self._required_run(scope.owner_user_id, run_id)
            run.cleanup_status = TranslationCleanupStatus.SUCCEEDED
            run.cleanup_error = None
            run.updated_at = datetime.now(UTC)
            await self.session.commit()
        except LinguaSpindleFailure as exc:
            run = await self._required_run(scope.owner_user_id, run_id)
            if exc.code == "linguaspindle_not_found":
                run.cleanup_status = TranslationCleanupStatus.SUCCEEDED
                run.cleanup_error = None
            else:
                run.cleanup_status = TranslationCleanupStatus.FAILED
                run.cleanup_error = "远端翻译项目清理失败。"
            run.updated_at = datetime.now(UTC)
            await self.session.commit()
            if not suppress_failure and exc.code != "linguaspindle_not_found":
                raise ApplicationError(
                    "translation_cleanup_failed",
                    "远端翻译项目清理失败，可稍后重试。",
                    status_code=503,
                ) from exc
        return run

    async def _ensure_remote(self, owner_user_id: UUID, run_id: UUID) -> EditionTranslationRunModel:
        run = await self._required_run(owner_user_id, run_id)
        if run.remote_project_id is None or run.remote_job_id is None:
            await self.provider_credentials.usable_bound_credential(
                run.provider_credential_version_id
            )
        request_id = self._request_id(run_id)
        try:
            if run.remote_project_id is None:
                source_file = await self.library.get_edition_file_for_owner(
                    owner_user_id,
                    run.source_edition_id,
                    run.source_edition_file_id,
                )
                source_edition = await self.session.get(BookEditionModel, run.source_edition_id)
                if source_file is None or source_edition is None:
                    raise ApplicationError(
                        "translation_source_snapshot_missing",
                        "翻译任务固定的原文文件已不可用。",
                        status_code=409,
                    )
                if (
                    source_file.edition_file.revision != run.source_revision
                    or source_file.stored_file.sha256 != run.source_sha256
                    or source_file.stored_file.file_format is not run.source_format
                ):
                    raise ApplicationError(
                        "translation_source_snapshot_mismatch",
                        "翻译任务固定的原文文件与任务快照不一致。",
                        status_code=409,
                    )
                storage_key = source_file.stored_file.storage_key
                format_contract = translation_format_contract(run.source_format)
                filename = f"source-r{run.source_revision}{format_contract.extension}"
                if (
                    run.source_format is FileFormat.EPUB
                    and PurePath(source_file.stored_file.original_filename).suffix.lower()
                    == format_contract.extension
                ):
                    filename = source_file.stored_file.original_filename
                await self.session.commit()
                try:
                    actual_sha256 = await to_thread.run_sync(
                        self.storage.calculate_checksum,
                        storage_key,
                    )
                    if actual_sha256 != run.source_sha256:
                        raise ApplicationError(
                            "source_file_integrity_error",
                            "原文文件完整性校验失败。",
                            status_code=409,
                        )
                    with self.storage.open_file(storage_key) as source_stream:
                        project = await self.client.create_project(
                            source=source_stream,
                            filename=filename,
                            source_format=run.source_format,
                            source_language=source_edition.language,
                            target_language=run.target_language,
                            idempotency_key=f"np:{run_id}:project:v1",
                            request_id=request_id,
                        )
                except StorageError as exc:
                    raise ApplicationError(
                        "source_file_unavailable", "原文文件不可用。", status_code=409
                    ) from exc
                run = await self._required_run(owner_user_id, run_id)
                run.remote_project_id = project.id
                run.remote_request_id = project.request_id
                run.updated_at = datetime.now(UTC)
                await self.session.commit()
            if run.remote_job_id is None:
                project_id = run.remote_project_id
                if project_id is None:
                    raise RuntimeError("remote project was not persisted")
                await self.session.commit()
                remote = await self.client.create_job(
                    project_id=project_id,
                    source_format=run.source_format,
                    credential_scope=str(run.provider_credential_version_id),
                    idempotency_key=f"np:{run_id}:job:v1",
                    request_id=request_id,
                )
                if remote.project_id != project_id:
                    raise LinguaSpindleFailure(
                        "translation_protocol_error",
                        "小说翻译服务返回了不兼容的响应。",
                        status_code=502,
                    )
                run = await self._required_run(owner_user_id, run_id)
                run.remote_job_id = remote.id
                self._apply_remote_fields(run, remote)
                await self.session.commit()
            return await self._required_run(owner_user_id, run_id)
        except (LinguaSpindleFailure, ApplicationError) as exc:
            await self._record_failure(owner_user_id, run_id, exc, phase="prepare")
            return await self._required_run(owner_user_id, run_id)

    async def _apply_remote_status(
        self,
        owner_user_id: UUID,
        run_id: UUID,
        remote: RemoteJob,
        *,
        retry_count: int | None = None,
    ) -> None:
        run = await self._required_run(owner_user_id, run_id)
        self._apply_remote_fields(run, remote)
        if retry_count is not None:
            run.retry_count = retry_count
        await self.session.commit()

    @staticmethod
    def _apply_remote_fields(run: EditionTranslationRunModel, remote: RemoteJob) -> None:
        now = datetime.now(UTC)
        run.remote_status = remote.status
        run.remote_request_id = remote.request_id or run.remote_request_id
        run.status = local_status_for_remote(remote.status)
        run.progress = remote.progress
        run.last_synced_at = now
        run.updated_at = now
        if run.started_at is None and remote.status not in {"queued", "cancelled"}:
            run.started_at = now
        if run.status in TERMINAL_TRANSLATION_RUN_STATUSES:
            run.completed_at = now
        if remote.error_code:
            run.error_code = f"linguaspindle_{remote.error_code}"
            run.error_message = "远端翻译任务未完整成功。"
            run.error_details = {}
        elif remote.status not in {"failed", "partially_succeeded"}:
            run.error_code = None
            run.error_message = None
            run.error_details = {}

    async def _record_failure(
        self,
        owner_user_id: UUID,
        run_id: UUID,
        error: LinguaSpindleFailure | ApplicationError,
        *,
        phase: str,
    ) -> None:
        await self.session.rollback()
        run = await self.runs.get(owner_user_id, run_id, for_update=True)
        if run is None or run.status is TranslationRunStatus.SUCCEEDED:
            return
        ambiguous = isinstance(error, LinguaSpindleFailure) and error.ambiguous
        retryable = isinstance(error, LinguaSpindleFailure) and error.retryable
        run.status = (
            TranslationRunStatus.ATTENTION_REQUIRED
            if ambiguous or phase == "sync"
            else TranslationRunStatus.FAILED
        )
        run.error_code = error.code
        run.error_message = error.message
        run.error_details = {"phase": phase, "retryable": retryable}
        run.updated_at = datetime.now(UTC)
        run.last_synced_at = run.updated_at
        if run.status is TranslationRunStatus.FAILED:
            run.completed_at = run.updated_at
        await self.session.commit()

    async def _required_run(self, owner_user_id: UUID, run_id: UUID) -> EditionTranslationRunModel:
        run = await self.runs.get(owner_user_id, run_id)
        if run is None:
            raise self._not_found()
        return run

    async def _validate_supersedes(
        self,
        scope: LibraryAccessScope,
        book_id: UUID,
        source_edition_id: UUID,
        supersedes_id: UUID | None,
    ) -> None:
        if supersedes_id is None:
            return
        edition = await self.editions.get_for_owner(scope.owner_user_id, supersedes_id)
        if edition is None:
            raise ApplicationError("edition_not_found", "要重翻的版本不存在。", status_code=404)
        if (
            edition.book_id != book_id
            or edition.content_role is not ContentRole.TRANSLATION
            or edition.source_edition_id != source_edition_id
        ):
            raise ApplicationError(
                "invalid_translation_supersedes",
                "要重翻的版本必须来自同一原文。",
                status_code=409,
            )
        if not scope.can_manage and (
            edition.created_by_user_id != scope.viewer_user_id
            or edition.creation_method is not CreationMethod.GENERATED
        ):
            raise ApplicationError(
                "translation_supersedes_forbidden",
                "只能重新翻译自己发起生成的译本。",
                status_code=403,
            )

    def _configuration_snapshot(
        self,
        status: LinguaServiceStatus,
        credential: ProviderCredentialVersionModel,
    ) -> dict[str, object]:
        if credential.algorithm == LEGACY_ALGORITHM:
            credential_provider = OPENAI_COMPATIBLE_PROVIDER
            credential_provider_name = PROVIDER_DISPLAY_NAMES[OPENAI_COMPATIBLE_PROVIDER]
            credential_base_url = self.settings.provider_relay_upstream_base_url
            credential_model = self.settings.provider_relay_allowed_models[0]
            thinking_enabled = False
        else:
            credential_provider = cast(ProviderKind, credential.provider)
            credential_provider_name = (
                credential.provider_name
                if credential_provider == CUSTOM_PROVIDER and credential.provider_name is not None
                else PROVIDER_DISPLAY_NAMES[credential_provider]
            )
            credential_base_url = credential.base_url
            credential_model = credential.model
            thinking_enabled = credential.thinking_enabled
        return {
            "contract": "novel-platform-linguaspindle.v2",
            "service_version": status.version,
            "source_format": status.source_format.value,
            "pipeline_key": status.pipeline_key,
            "pipeline_version": status.pipeline_version,
            "provider_id": status.provider_id,
            "provider_model": credential_model,
            "profile_id": self.settings.linguaspindle_profile_id,
            "credential_provider": credential_provider,
            "credential_provider_name": credential_provider_name,
            "credential_base_url": credential_base_url,
            "thinking_enabled": thinking_enabled,
            "credential_version": credential.version,
        }

    @staticmethod
    def _require_same_request(
        run: EditionTranslationRunModel,
        book_id: UUID,
        source_edition_id: UUID,
        command: CreateTranslationRun,
    ) -> None:
        if (
            run.book_id != book_id
            or run.source_edition_id != source_edition_id
            or run.target_language != command.target_language.strip()
            or run.edition_title != command.edition_title.strip()
            or run.supersedes_edition_id != command.supersedes_edition_id
        ):
            raise ApplicationError(
                "translation_client_request_conflict",
                "该请求 ID 已用于不同的翻译任务。",
                status_code=409,
            )

    @staticmethod
    def _require_translation(scope: LibraryAccessScope) -> None:
        if not scope.has(CredentialCapability.TRANSLATION_USE):
            raise ApplicationError(
                "library_capability_required",
                "当前访问凭证不包含小说翻译能力。",
                status_code=403,
                details={"capability": CredentialCapability.TRANSLATION_USE.value},
            )

    @staticmethod
    def _request_id(run_id: UUID) -> str:
        return f"np-{run_id}"

    @staticmethod
    def _not_found() -> ApplicationError:
        return ApplicationError("translation_run_not_found", "翻译任务不存在。", status_code=404)
