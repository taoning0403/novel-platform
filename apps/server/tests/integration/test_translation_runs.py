import hashlib
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, BinaryIO, cast
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import func, select

from novel_platform.api.dependencies.translation import get_linguaspindle_client
from novel_platform.config import get_settings
from novel_platform.domain.editions.models import (
    ContentRole,
    CreationMethod,
    EditionStatus,
    TranslationOrigin,
)
from novel_platform.infrastructure.database.models import (
    BookEditionModel,
    EditionTranslationRunModel,
    ReadingProgressModel,
    StoredFileModel,
    UserBookPreferenceModel,
)
from novel_platform.infrastructure.integrations.linguaspindle import (
    DownloadedArtifact,
    LinguaServiceStatus,
    RemoteArtifact,
    RemoteJob,
    RemoteProject,
)
from novel_platform.main import app


class FakeLinguaSpindle:
    def __init__(self) -> None:
        self.projects_by_key: dict[str, RemoteProject] = {}
        self.jobs_by_key: dict[str, RemoteJob] = {}
        self.jobs: dict[str, RemoteJob] = {}
        self.sources: dict[str, bytes] = {}
        self.control_keys: list[tuple[str, str, str | None]] = []
        self.deleted_projects: list[str] = []
        self.corrupt_download_jobs: set[str] = set()
        self.translated_text = b"Chapter 1\n\nTranslated body.\n"

    async def service_status(self, *, request_id: str) -> LinguaServiceStatus:
        return LinguaServiceStatus(
            enabled=True,
            available=True,
            version="0.3.1",
            pipeline_key="novel_txt_v1",
            pipeline_version="1",
            provider_id="mock",
            provider_name="Mock Provider",
            provider_model="mock-v1",
            provider_offline=True,
            idempotency_required=True,
        )

    async def create_project(
        self,
        *,
        source: BinaryIO,
        filename: str,
        source_language: str,
        target_language: str,
        idempotency_key: str,
        request_id: str,
    ) -> RemoteProject:
        existing = self.projects_by_key.get(idempotency_key)
        if existing is not None:
            return existing
        project = RemoteProject(
            id=f"project-{len(self.projects_by_key) + 1}",
            request_id=request_id,
        )
        self.projects_by_key[idempotency_key] = project
        self.sources[project.id] = source.read()
        return project

    async def create_job(
        self,
        *,
        project_id: str,
        idempotency_key: str,
        request_id: str,
    ) -> RemoteJob:
        existing = self.jobs_by_key.get(idempotency_key)
        if existing is not None:
            return existing
        job = RemoteJob(
            id=f"job-{len(self.jobs_by_key) + 1}",
            project_id=project_id,
            status="queued",
            progress=0,
            request_id=request_id,
        )
        self.jobs_by_key[idempotency_key] = job
        self.jobs[job.id] = job
        return job

    async def get_job(self, job_id: str, *, request_id: str) -> RemoteJob:
        return self.jobs[job_id]

    async def control_job(
        self,
        job_id: str,
        action: str,
        *,
        request_id: str,
        idempotency_key: str | None = None,
    ) -> RemoteJob:
        self.control_keys.append((job_id, action, idempotency_key))
        statuses = {
            "pause": "paused",
            "resume": "running",
            "cancel": "cancelled",
            "retry": "queued",
        }
        current = self.jobs[job_id]
        updated = RemoteJob(
            id=current.id,
            project_id=current.project_id,
            status=statuses[action],
            progress=0 if action == "retry" else current.progress,
            request_id=request_id,
        )
        self.jobs[job_id] = updated
        return updated

    async def list_artifacts(
        self,
        project_id: str,
        job_id: str,
        *,
        request_id: str,
    ) -> list[RemoteArtifact]:
        return [
            RemoteArtifact(
                id=f"artifact-{job_id}",
                project_id=project_id,
                job_id=job_id,
                kind="novel_export_txt",
                filename="translated.txt",
                media_type="text/plain; charset=utf-8",
                size=len(self.translated_text),
                checksum=hashlib.sha256(self.translated_text).hexdigest(),
                download_url=f"/api/artifacts/artifact-{job_id}/download",
            )
        ]

    async def download_artifact(
        self,
        artifact: RemoteArtifact,
        destination: BinaryIO,
        *,
        request_id: str,
        max_bytes: int,
    ) -> DownloadedArtifact:
        assert len(self.translated_text) <= max_bytes
        destination.write(self.translated_text)
        checksum = hashlib.sha256(self.translated_text).hexdigest()
        if artifact.job_id in self.corrupt_download_jobs:
            checksum = "0" * 64
        return DownloadedArtifact(size=len(self.translated_text), sha256=checksum)

    async def delete_project(self, project_id: str, *, request_id: str) -> None:
        self.deleted_projects.append(project_id)

    def set_status(self, job_id: str, status: str, *, progress: float = 1) -> None:
        current = self.jobs[job_id]
        self.jobs[job_id] = RemoteJob(
            id=current.id,
            project_id=current.project_id,
            status=status,
            progress=progress,
            request_id=current.request_id,
            error_code="mock_failure" if status in {"failed", "partially_succeeded"} else None,
        )


async def create_reader_login(
    app_harness,
    admin_headers: dict[str, str],
    *,
    name: str,
    capabilities: list[str],
) -> tuple[dict[str, Any], dict[str, str]]:
    created = await app_harness.client.post(
        "/api/v1/admin/readers",
        headers=admin_headers,
        json={
            "display_name": name,
            "expires_at": (datetime.now(UTC) + timedelta(days=30)).isoformat(),
            "capabilities": capabilities,
        },
    )
    assert created.status_code == 201, created.text
    logged_in = await app_harness.client.post(
        "/api/v1/auth/login",
        json={
            "credential": created.json()["access_credential"],
            "refresh_token_delivery": "body",
            "device": {
                "client_instance_id": str(uuid4()),
                "name": f"{name}的测试设备",
                "platform": "web",
                "app_version": "0.9.0-test",
            },
        },
    )
    assert logged_in.status_code == 200, logged_in.text
    return cast(dict[str, Any], created.json()["reader"]), {
        "Authorization": f"Bearer {logged_in.json()['access_token']}"
    }


async def create_txt_book(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    *,
    title: str,
) -> dict[str, Any]:
    inspected = await client.post(
        "/api/v1/imports/inspect",
        headers=headers,
        data={"operation": "create_book", "text_encoding": "auto"},
        files={"file": (f"{title}.txt", f"第一章\n{title}正文".encode(), "text/plain")},
    )
    assert inspected.status_code == 201, inspected.text
    committed = await client.post(
        f"/api/v1/imports/{inspected.json()['id']}/commit",
        headers=headers,
        json={
            "canonical_title": title,
            "edition_title": f"{title}原文",
            "language": "zh-CN",
            "content_role": "source",
        },
    )
    assert committed.status_code == 200, committed.text
    return cast(dict[str, Any], committed.json())


def configure_fake(app_harness, fake: FakeLinguaSpindle) -> None:
    settings = app_harness.settings.model_copy(
        update={
            "linguaspindle_enabled": True,
            "linguaspindle_provider_id": "mock",
            "linguaspindle_max_download_bytes": 1024 * 1024,
        }
    )
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_linguaspindle_client] = lambda: fake


async def create_run(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    *,
    book_id: str,
    source_edition_id: str,
    target_language: str = "en",
    client_request_id: UUID | None = None,
    supersedes_edition_id: str | None = None,
) -> httpx.Response:
    payload: dict[str, str] = {
        "target_language": target_language,
        "edition_title": f"{target_language} 机器译本",
        "client_request_id": str(client_request_id or uuid4()),
    }
    if supersedes_edition_id is not None:
        payload["supersedes_edition_id"] = supersedes_edition_id
    return await client.post(
        f"/api/v1/books/{book_id}/editions/{source_edition_id}/translation-runs",
        headers=headers,
        json=payload,
    )


@pytest.mark.integration
async def test_translation_capability_idempotency_isolation_and_retry(
    app_harness,
    tmp_path: Path,
) -> None:
    fake = FakeLinguaSpindle()
    configure_fake(app_harness, fake)
    client = app_harness.client
    admin = await app_harness.provision_admin()
    _, read_headers = await create_reader_login(
        app_harness,
        admin.headers,
        name="只读者",
        capabilities=["library.read"],
    )
    _, upload_headers = await create_reader_login(
        app_harness,
        admin.headers,
        name="上传者",
        capabilities=["library.read", "library.upload"],
    )
    _, translator_headers = await create_reader_login(
        app_harness,
        admin.headers,
        name="翻译者",
        capabilities=["library.read", "translation.use"],
    )
    _, other_headers = await create_reader_login(
        app_harness,
        admin.headers,
        name="其他翻译者",
        capabilities=["library.read", "translation.use"],
    )
    _, combined_headers = await create_reader_login(
        app_harness,
        admin.headers,
        name="上传翻译者",
        capabilities=["library.read", "library.upload", "translation.use"],
    )
    created = await create_txt_book(client, admin.headers, title="幂等测试书")
    book_id = created["book"]["id"]
    source_id = created["edition"]["id"]

    for headers in (read_headers, upload_headers):
        denied = await create_run(
            client,
            headers,
            book_id=book_id,
            source_edition_id=source_id,
        )
        assert denied.status_code == 403
        assert denied.json()["error"]["code"] == "library_capability_required"

    service_status = await client.get(
        "/api/v1/translation-service/status",
        headers=combined_headers,
    )
    assert service_status.status_code == 200
    assert service_status.json()["available"] is True
    combined_upload = await client.post(
        "/api/v1/imports/inspect",
        headers=combined_headers,
        data={"operation": "create_book", "text_encoding": "auto"},
        files={"file": ("combined.txt", b"combined", "text/plain")},
    )
    assert combined_upload.status_code == 201
    assert (
        await client.delete(
            f"/api/v1/imports/{combined_upload.json()['id']}",
            headers=combined_headers,
        )
    ).status_code == 204

    request_id = uuid4()
    first = await create_run(
        client,
        translator_headers,
        book_id=book_id,
        source_edition_id=source_id,
        client_request_id=request_id,
    )
    assert first.status_code == 201, first.text
    run = first.json()
    assert run["status"] == "queued"
    assert run["creator"] == {"display_name": "翻译者"}
    assert len(fake.projects_by_key) == len(fake.jobs_by_key) == 1
    assert next(iter(fake.projects_by_key)).endswith(":project:v1")
    assert next(iter(fake.jobs_by_key)).endswith(":job:v1")

    replay = await create_run(
        client,
        translator_headers,
        book_id=book_id,
        source_edition_id=source_id,
        client_request_id=request_id,
    )
    assert replay.status_code == 201
    assert replay.json()["id"] == run["id"]
    assert len(fake.projects_by_key) == len(fake.jobs_by_key) == 1

    conflict = await create_run(
        client,
        translator_headers,
        book_id=book_id,
        source_edition_id=source_id,
    )
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "translation_run_already_active"
    assert (
        await client.get(f"/api/v1/translation-runs/{run['id']}", headers=other_headers)
    ).status_code == 404
    assert (
        await client.get(f"/api/v1/translation-runs/{run['id']}", headers=admin.headers)
    ).status_code == 200

    fake.set_status(run["remote_job_id"], "failed")
    failed = await client.post(
        f"/api/v1/translation-runs/{run['id']}/sync",
        headers=translator_headers,
    )
    assert failed.status_code == 200
    assert failed.json()["status"] == "failed"
    retried = await client.post(
        f"/api/v1/translation-runs/{run['id']}/retry",
        headers=translator_headers,
    )
    assert retried.status_code == 200
    assert retried.json()["status"] == "queued"
    assert fake.control_keys[-1] == (
        run["remote_job_id"],
        "retry",
        f"np:{run['id']}:retry:1:v1",
    )


@pytest.mark.integration
async def test_successful_translation_ingestion_draft_visibility_publication_and_deletion(
    app_harness,
    tmp_path: Path,
) -> None:
    fake = FakeLinguaSpindle()
    configure_fake(app_harness, fake)
    client = app_harness.client
    admin = await app_harness.provision_admin()
    translator, translator_headers = await create_reader_login(
        app_harness,
        admin.headers,
        name="译者甲",
        capabilities=["library.read", "translation.use"],
    )
    other, other_headers = await create_reader_login(
        app_harness,
        admin.headers,
        name="读者乙",
        capabilities=["library.read", "translation.use"],
    )
    created = await create_txt_book(client, admin.headers, title="生成译本测试书")
    book_id = created["book"]["id"]
    source_id = created["edition"]["id"]

    started = await create_run(
        client,
        translator_headers,
        book_id=book_id,
        source_edition_id=source_id,
    )
    assert started.status_code == 201, started.text
    run = started.json()
    fake.set_status(run["remote_job_id"], "succeeded")
    synced = await client.post(
        f"/api/v1/translation-runs/{run['id']}/sync",
        headers=translator_headers,
    )
    assert synced.status_code == 200, synced.text
    completed = synced.json()
    generated_id = completed["generated_edition_id"]
    assert completed["status"] == "succeeded"
    assert completed["cleanup_status"] == "succeeded"
    assert completed["can_preview_draft"] is True
    assert completed["can_publish"] is False
    assert fake.deleted_projects == [run["remote_project_id"]]
    admin_run = await client.get(
        f"/api/v1/translation-runs/{run['id']}",
        headers=admin.headers,
    )
    assert admin_run.status_code == 200
    assert admin_run.json()["can_publish"] is True

    creator_detail = await client.get(f"/api/v1/books/{book_id}", headers=translator_headers)
    assert creator_detail.status_code == 200
    creator_editions = {item["id"]: item for item in creator_detail.json()["editions"]}
    assert creator_editions[generated_id]["status"] == "draft"
    other_detail = await client.get(f"/api/v1/books/{book_id}", headers=other_headers)
    assert other_detail.status_code == 200
    assert generated_id not in {item["id"] for item in other_detail.json()["editions"]}
    creator_open = await client.post(
        f"/api/v1/editions/{generated_id}/reader/open",
        headers=translator_headers,
    )
    assert creator_open.status_code == 200, creator_open.text
    assert (
        await client.post(
            f"/api/v1/editions/{generated_id}/reader/open",
            headers=other_headers,
        )
    ).status_code == 404

    published = await client.patch(
        f"/api/v1/books/{book_id}/editions/{generated_id}",
        headers=admin.headers,
        json={"status": "ready"},
    )
    assert published.status_code == 200, published.text
    assert published.json()["status"] == "ready"
    assert (
        await client.post(
            f"/api/v1/editions/{generated_id}/reader/open",
            headers=other_headers,
        )
    ).status_code == 200

    async with app_harness.session_factory() as session:
        old_progress = await session.get(
            ReadingProgressModel,
            (UUID(other["id"]), UUID(generated_id)),
        )
        old_preference = await session.get(
            UserBookPreferenceModel,
            (UUID(other["id"]), UUID(book_id)),
        )
        assert old_progress is not None and old_preference is not None
        old_progress_version = old_progress.version
        assert old_preference.last_opened_edition_id == UUID(generated_id)

    retranslation = await create_run(
        client,
        translator_headers,
        book_id=book_id,
        source_edition_id=source_id,
        supersedes_edition_id=generated_id,
    )
    assert retranslation.status_code == 201, retranslation.text
    rerun = retranslation.json()
    fake.set_status(rerun["remote_job_id"], "succeeded")
    resynced = await client.post(
        f"/api/v1/translation-runs/{rerun['id']}/sync",
        headers=translator_headers,
    )
    assert resynced.status_code == 200, resynced.text
    replacement_id = resynced.json()["generated_edition_id"]
    assert replacement_id != generated_id
    assert fake.deleted_projects == [
        run["remote_project_id"],
        rerun["remote_project_id"],
    ]
    assert (
        await client.get(
            f"/api/v1/books/{book_id}/editions/{replacement_id}",
            headers=translator_headers,
        )
    ).status_code == 200
    assert (
        await client.get(
            f"/api/v1/books/{book_id}/editions/{replacement_id}",
            headers=other_headers,
        )
    ).status_code == 404

    async with app_harness.session_factory() as session:
        edition = await session.get(BookEditionModel, UUID(generated_id))
        replacement = await session.get(BookEditionModel, UUID(replacement_id))
        old_progress = await session.get(
            ReadingProgressModel,
            (UUID(other["id"]), UUID(generated_id)),
        )
        old_preference = await session.get(
            UserBookPreferenceModel,
            (UUID(other["id"]), UUID(book_id)),
        )
        stored_files = list(
            (
                await session.scalars(
                    select(StoredFileModel).where(
                        StoredFileModel.created_by_user_id == UUID(translator["id"])
                    )
                )
            ).all()
        )
        assert edition is not None
        assert edition.content_role is ContentRole.TRANSLATION
        assert edition.translation_origin is TranslationOrigin.AI
        assert edition.creation_method is CreationMethod.GENERATED
        assert edition.source_edition_id == UUID(source_id)
        assert edition.status is EditionStatus.READY
        assert replacement is not None
        assert replacement.status is EditionStatus.DRAFT
        assert replacement.source_edition_id == UUID(source_id)
        assert replacement.supersedes_edition_id == UUID(generated_id)
        assert old_progress is not None and old_progress.version == old_progress_version
        assert old_preference is not None
        assert old_preference.last_opened_edition_id == UUID(generated_id)
        assert stored_files and all(item.owner_user_id == admin.user_id for item in stored_files)

    deleted = await client.delete(
        f"/api/v1/books/{book_id}/editions/{replacement_id}",
        headers=translator_headers,
    )
    assert deleted.status_code == 204, deleted.text
    retained = await client.get(
        f"/api/v1/translation-runs/{rerun['id']}",
        headers=translator_headers,
    )
    assert retained.status_code == 200
    assert retained.json()["generated_edition_id"] is None
    async with app_harness.session_factory() as session:
        stored_run = await session.get(EditionTranslationRunModel, UUID(rerun["id"]))
        assert stored_run is not None and stored_run.generated_edition_id is None


@pytest.mark.integration
async def test_partial_or_corrupt_translation_never_creates_an_edition(
    app_harness,
    tmp_path: Path,
) -> None:
    fake = FakeLinguaSpindle()
    configure_fake(app_harness, fake)
    client = app_harness.client
    admin = await app_harness.provision_admin()
    _, translator_headers = await create_reader_login(
        app_harness,
        admin.headers,
        name="失败场景译者",
        capabilities=["library.read", "translation.use"],
    )
    created = await create_txt_book(client, admin.headers, title="失败补偿测试书")
    book_id = created["book"]["id"]
    source_id = created["edition"]["id"]

    partial = await create_run(
        client,
        translator_headers,
        book_id=book_id,
        source_edition_id=source_id,
        target_language="ja",
    )
    assert partial.status_code == 201, partial.text
    partial_run = partial.json()
    fake.set_status(partial_run["remote_job_id"], "partially_succeeded", progress=0.8)
    partial_sync = await client.post(
        f"/api/v1/translation-runs/{partial_run['id']}/sync",
        headers=translator_headers,
    )
    assert partial_sync.status_code == 200
    assert partial_sync.json()["status"] == "partially_succeeded"
    assert partial_sync.json()["generated_edition_id"] is None

    corrupt = await create_run(
        client,
        translator_headers,
        book_id=book_id,
        source_edition_id=source_id,
        target_language="fr",
    )
    assert corrupt.status_code == 201, corrupt.text
    corrupt_run = corrupt.json()
    fake.set_status(corrupt_run["remote_job_id"], "succeeded")
    fake.corrupt_download_jobs.add(corrupt_run["remote_job_id"])
    corrupt_sync = await client.post(
        f"/api/v1/translation-runs/{corrupt_run['id']}/sync",
        headers=translator_headers,
    )
    assert corrupt_sync.status_code == 200, corrupt_sync.text
    assert corrupt_sync.json()["status"] == "attention_required"
    assert corrupt_sync.json()["error_code"] == "translation_artifact_integrity_error"
    assert corrupt_sync.json()["generated_edition_id"] is None

    async with app_harness.session_factory() as session:
        generated_count = await session.scalar(
            select(func.count(BookEditionModel.id)).where(
                BookEditionModel.book_id == UUID(book_id),
                BookEditionModel.creation_method == CreationMethod.GENERATED,
            )
        )
        progress_count = await session.scalar(
            select(func.count(ReadingProgressModel.user_id)).where(
                ReadingProgressModel.edition_id.not_in([UUID(source_id)])
            )
        )
        assert generated_count == 0
        assert progress_count == 0
