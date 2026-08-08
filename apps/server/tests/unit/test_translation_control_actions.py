from types import SimpleNamespace
from typing import BinaryIO, cast
from uuid import UUID, uuid4

import pytest

from novel_platform.api.translation_responses import _available_actions
from novel_platform.application.access import LibraryAccessScope
from novel_platform.application.errors import ApplicationError
from novel_platform.application.translations.service import TranslationRunService
from novel_platform.domain.library.models import FileFormat
from novel_platform.domain.translations.control import control_actions_for_status
from novel_platform.domain.translations.models import (
    TranslationCleanupStatus,
    TranslationRunStatus,
)
from novel_platform.infrastructure.database.models import EditionTranslationRunModel
from novel_platform.infrastructure.integrations.linguaspindle import (
    DownloadedArtifact,
    LinguaServiceStatus,
    LinguaSpindleGateway,
    RemoteArtifact,
    RemoteJob,
    RemoteProject,
)


def _run(
    status: TranslationRunStatus,
    *,
    remote_job_id: str | None = None,
    remote_project_id: str | None = None,
    cleanup_status: TranslationCleanupStatus = TranslationCleanupStatus.NOT_REQUIRED,
) -> EditionTranslationRunModel:
    return cast(
        EditionTranslationRunModel,
        SimpleNamespace(
            status=status,
            remote_job_id=remote_job_id,
            remote_project_id=remote_project_id,
            cleanup_status=cleanup_status,
            retry_count=0,
        ),
    )


def _scope() -> LibraryAccessScope:
    user_id = uuid4()
    return LibraryAccessScope(
        viewer_user_id=user_id,
        owner_user_id=user_id,
        can_manage=True,
        capabilities=frozenset(),
    )


class _ControlClient(LinguaSpindleGateway):
    def __init__(self, remote: RemoteJob) -> None:
        self.remote = remote
        self.control_calls: list[tuple[str, str, str, str | None]] = []

    async def service_status(
        self,
        *,
        source_format: FileFormat,
        request_id: str,
    ) -> LinguaServiceStatus:
        raise AssertionError("control test must not request service status")

    async def create_project(
        self,
        *,
        source: BinaryIO,
        filename: str,
        source_format: FileFormat,
        source_language: str,
        target_language: str,
        idempotency_key: str,
        request_id: str,
    ) -> RemoteProject:
        raise AssertionError("control test must not create a project")

    async def create_job(
        self,
        *,
        project_id: str,
        source_format: FileFormat,
        credential_scope: str,
        idempotency_key: str,
        request_id: str,
    ) -> RemoteJob:
        raise AssertionError("control test must not create a job")

    async def get_job(self, job_id: str, *, request_id: str) -> RemoteJob:
        raise AssertionError("control test must not fetch a job")

    async def control_job(
        self,
        job_id: str,
        action: str,
        *,
        request_id: str,
        idempotency_key: str | None = None,
    ) -> RemoteJob:
        self.control_calls.append((job_id, action, request_id, idempotency_key))
        return self.remote

    async def list_artifacts(
        self,
        project_id: str,
        job_id: str,
        *,
        request_id: str,
    ) -> list[RemoteArtifact]:
        raise AssertionError("control test must not list artifacts")

    async def download_artifact(
        self,
        artifact: RemoteArtifact,
        destination: BinaryIO,
        *,
        request_id: str,
        max_bytes: int,
    ) -> DownloadedArtifact:
        raise AssertionError("control test must not download an artifact")

    async def delete_project(self, project_id: str, *, request_id: str) -> None:
        raise AssertionError("control test must not delete a project")


class _ControlService(TranslationRunService):
    def __init__(self, run: EditionTranslationRunModel, remote: RemoteJob) -> None:
        self.run = run
        self.control_client = _ControlClient(remote)
        self.client = self.control_client
        self.applied_remote_statuses: list[tuple[UUID, UUID, RemoteJob, int | None]] = []

    async def get(
        self,
        scope: LibraryAccessScope,
        run_id: UUID,
    ) -> EditionTranslationRunModel:
        return self.run

    async def _apply_remote_status(
        self,
        owner_user_id: UUID,
        run_id: UUID,
        remote: RemoteJob,
        *,
        retry_count: int | None = None,
    ) -> None:
        self.applied_remote_statuses.append(
            (owner_user_id, run_id, remote, retry_count),
        )

    async def _required_run(
        self,
        owner_user_id: UUID,
        run_id: UUID,
    ) -> EditionTranslationRunModel:
        return self.run


def _service_for_control(
    run: EditionTranslationRunModel,
    *,
    remote_status: str,
) -> _ControlService:
    remote = RemoteJob(
        id=cast(str, run.remote_job_id),
        project_id=cast(str, run.remote_project_id),
        status=remote_status,
        progress=0,
        request_id="remote-request",
    )
    return _ControlService(run, remote)


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (TranslationRunStatus.PREPARING, ["cancel"]),
        (TranslationRunStatus.QUEUED, ["pause", "cancel"]),
        (TranslationRunStatus.RUNNING, ["pause", "cancel"]),
        (TranslationRunStatus.PAUSED, ["resume", "cancel"]),
        (TranslationRunStatus.CANCELLING, ["cancel"]),
        (TranslationRunStatus.CANCELLED, []),
        (TranslationRunStatus.PARTIALLY_SUCCEEDED, ["retry"]),
        (TranslationRunStatus.FAILED, ["retry"]),
        (TranslationRunStatus.INGESTING, []),
        (TranslationRunStatus.SUCCEEDED, []),
        (TranslationRunStatus.ATTENTION_REQUIRED, ["cancel"]),
    ],
)
def test_available_control_actions_preserve_status_matrix_and_order(
    status: TranslationRunStatus,
    expected: list[str],
) -> None:
    assert list(control_actions_for_status(status)) == expected
    assert _available_actions(_run(status)) == expected


@pytest.mark.parametrize(
    ("status", "cleanup_status", "expected"),
    [
        (
            TranslationRunStatus.RUNNING,
            TranslationCleanupStatus.NOT_REQUIRED,
            ["pause", "cancel", "sync"],
        ),
        (
            TranslationRunStatus.FAILED,
            TranslationCleanupStatus.PENDING,
            ["retry", "sync", "cleanup"],
        ),
        (
            TranslationRunStatus.CANCELLED,
            TranslationCleanupStatus.FAILED,
            ["sync", "cleanup"],
        ),
        (
            TranslationRunStatus.SUCCEEDED,
            TranslationCleanupStatus.PENDING,
            ["cleanup"],
        ),
        (
            TranslationRunStatus.SUCCEEDED,
            TranslationCleanupStatus.SUCCEEDED,
            [],
        ),
    ],
)
def test_available_actions_preserve_remote_sync_and_cleanup_order(
    status: TranslationRunStatus,
    cleanup_status: TranslationCleanupStatus,
    expected: list[str],
) -> None:
    run = _run(
        status,
        remote_job_id="job-1",
        remote_project_id="project-1",
        cleanup_status=cleanup_status,
    )

    assert _available_actions(run) == expected


@pytest.mark.parametrize(
    ("status", "action", "remote_status"),
    [
        (TranslationRunStatus.QUEUED, "pause", "paused"),
        (TranslationRunStatus.PAUSED, "resume", "running"),
        (TranslationRunStatus.QUEUED, "cancel", "cancelled"),
    ],
)
@pytest.mark.asyncio
async def test_translation_control_forwards_allowed_action_to_remote_job(
    status: TranslationRunStatus,
    action: str,
    remote_status: str,
) -> None:
    run_id = uuid4()
    run = _run(
        status,
        remote_job_id="job-1",
        remote_project_id="project-1",
    )
    service = _service_for_control(
        run,
        remote_status=remote_status,
    )
    scope = _scope()

    result = await service.control(scope, run_id, action)

    assert result is run
    assert service.control_client.control_calls == [
        ("job-1", action, f"np-{run_id}", None),
    ]
    assert service.applied_remote_statuses == [
        (scope.owner_user_id, run_id, service.control_client.remote, None),
    ]


@pytest.mark.asyncio
async def test_translation_control_preserves_conflict_error_contract() -> None:
    run = _run(
        TranslationRunStatus.QUEUED,
        remote_job_id="job-1",
        remote_project_id="project-1",
    )
    service = _service_for_control(
        run,
        remote_status="queued",
    )

    with pytest.raises(ApplicationError) as error:
        await service.control(_scope(), uuid4(), "resume")

    assert error.value.code == "translation_control_conflict"
    assert error.value.message == "翻译任务当前不能执行该操作。"
    assert error.value.status_code == 409
    assert service.control_client.control_calls == []
    assert service.applied_remote_statuses == []
