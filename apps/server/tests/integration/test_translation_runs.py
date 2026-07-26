import base64
import hashlib
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, BinaryIO, cast
from uuid import UUID, uuid4

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import func, select

from novel_platform import relay as provider_relay_module
from novel_platform.api.dependencies.translation import get_linguaspindle_client
from novel_platform.application.auth.admin_service import AdminService
from novel_platform.application.provider_credentials.service import (
    ProviderCredentialService,
    ProviderModels,
)
from novel_platform.config import ProviderRelaySettings, get_settings
from novel_platform.domain.editions.models import (
    ContentRole,
    CreationMethod,
    EditionStatus,
    TranslationOrigin,
)
from novel_platform.infrastructure.database.models import (
    BookEditionModel,
    EditionTranslationRunModel,
    ProviderCredentialVersionModel,
    ProviderUsageRecordModel,
    ReadingProgressModel,
    StoredFileModel,
    UserBookPreferenceModel,
)
from novel_platform.infrastructure.integrations.linguaspindle import (
    DownloadedArtifact,
    LinguaServiceStatus,
    LinguaSpindleFailure,
    RemoteArtifact,
    RemoteJob,
    RemoteProject,
)
from novel_platform.infrastructure.repositories.provider_credentials import (
    ProviderCredentialRepository,
)
from novel_platform.main import app
from novel_platform.relay import app as provider_relay_app
from novel_platform.relay import get_relay_session


class FakeLinguaSpindle:
    def __init__(self) -> None:
        self.projects_by_key: dict[str, RemoteProject] = {}
        self.jobs_by_key: dict[str, RemoteJob] = {}
        self.jobs: dict[str, RemoteJob] = {}
        self.sources: dict[str, bytes] = {}
        self.control_keys: list[tuple[str, str, str | None]] = []
        self.credential_scopes: list[str] = []
        self.deleted_projects: list[str] = []
        self.corrupt_download_jobs: set[str] = set()
        self.translated_text = b"Chapter 1\n\nTranslated body.\n"
        self.before_control: Callable[[str, str], Awaitable[None]] | None = None
        self.control_failure: LinguaSpindleFailure | None = None

    async def service_status(self, *, request_id: str) -> LinguaServiceStatus:
        return LinguaServiceStatus(
            enabled=True,
            available=True,
            version="0.3.2",
            pipeline_key="novel_txt_v1",
            pipeline_version="1",
            provider_id="openai-compatible",
            provider_name="Fake OpenAI-compatible Relay",
            provider_model="gpt-4.1-mini",
            provider_offline=False,
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
        credential_scope: str,
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
        self.credential_scopes.append(credential_scope)
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
        if self.before_control is not None:
            await self.before_control(job_id, action)
        if self.control_failure is not None:
            raise self.control_failure
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
    headers = {"Authorization": f"Bearer {logged_in.json()['access_token']}"}
    if "translation.use" in capabilities:
        configured = await app_harness.client.put(
            "/api/v1/me/provider-credential",
            headers=headers,
            json={
                "model": "gpt-4.1-mini",
                "api_key": f"sk-test-{uuid4()}",
            },
        )
        assert configured.status_code == 200, configured.text
    return cast(dict[str, Any], created.json()["reader"]), headers


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
            "linguaspindle_provider_id": "openai-compatible",
            "linguaspindle_max_download_bytes": 1024 * 1024,
            "provider_credential_master_key": SecretStr(
                base64.b64encode(bytes(range(32))).decode()
            ),
            "provider_relay_upstream_base_url": "https://provider.example/v1",
            "provider_relay_custom_allowed_base_urls": ["https://provider.example/v1"],
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
async def test_provider_model_discovery_contract_capability_and_no_persistence(
    app_harness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeLinguaSpindle()
    configure_fake(app_harness, fake)
    admin = await app_harness.provision_admin()
    reader, translator_headers = await create_reader_login(
        app_harness,
        admin.headers,
        name="模型发现译者",
        capabilities=["library.read", "translation.use"],
    )
    _, read_only_headers = await create_reader_login(
        app_harness,
        admin.headers,
        name="模型发现受限读者",
        capabilities=["library.read"],
    )
    captured: list[dict[str, str | None]] = []

    async def discover_models(
        _service: ProviderCredentialService,
        *,
        provider: str,
        base_url: str | None,
        api_key: str,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> ProviderModels:
        assert transport is None
        captured.append(
            {
                "provider": provider,
                "base_url": base_url,
                "api_key": api_key,
            }
        )
        return ProviderModels(
            provider=cast(Any, provider),
            models=["model-a", "model-b"],
        )

    monkeypatch.setattr(ProviderCredentialService, "discover_models", discover_models)

    unauthenticated = await app_harness.client.post(
        "/api/v1/me/provider-credential/models",
        json={"provider": "deepseek", "api_key": "sk-unauthenticated"},
    )
    assert unauthenticated.status_code == 401
    assert "sk-unauthenticated" not in unauthenticated.text

    forbidden = await app_harness.client.post(
        "/api/v1/me/provider-credential/models",
        headers=read_only_headers,
        json={"provider": "deepseek", "api_key": "sk-forbidden"},
    )
    assert forbidden.status_code == 403
    assert "sk-forbidden" not in forbidden.text

    invalid_preset = await app_harness.client.post(
        "/api/v1/me/provider-credential/models",
        headers=translator_headers,
        json={
            "provider": "kimi",
            "base_url": "https://attacker.example/v1",
            "api_key": "sk-invalid-preset",
        },
    )
    assert invalid_preset.status_code == 422
    assert "sk-invalid-preset" not in invalid_preset.text
    assert "attacker.example" not in invalid_preset.text

    discovered = await app_harness.client.post(
        "/api/v1/me/provider-credential/models",
        headers=translator_headers,
        json={
            "provider": "custom",
            "base_url": " https://provider.example/v1 ",
            "api_key": "sk-transient-discovery",
        },
    )
    assert discovered.status_code == 200, discovered.text
    assert discovered.headers["Cache-Control"] == "no-store"
    assert discovered.json() == {
        "provider": "custom",
        "models": ["model-a", "model-b"],
    }
    assert "sk-transient-discovery" not in discovered.text
    assert captured == [
        {
            "provider": "custom",
            "base_url": "https://provider.example/v1",
            "api_key": "sk-transient-discovery",
        }
    ]

    missing_model = await app_harness.client.put(
        "/api/v1/me/provider-credential",
        headers=translator_headers,
        json={
            "provider": "openai_compatible",
            "api_key": "sk-missing-explicit-model",
        },
    )
    assert missing_model.status_code == 422
    assert "sk-missing-explicit-model" not in missing_model.text

    async with app_harness.session_factory() as session:
        version_count = await session.scalar(
            select(func.count())
            .select_from(ProviderCredentialVersionModel)
            .where(ProviderCredentialVersionModel.user_id == UUID(reader["id"]))
        )
    assert version_count == 1


@pytest.mark.integration
async def test_provider_credential_rotation_scopes_runs_and_removal_revokes_versions(
    app_harness,
) -> None:
    fake = FakeLinguaSpindle()
    configure_fake(app_harness, fake)
    client = app_harness.client
    admin = await app_harness.provision_admin()
    reader, translator_headers = await create_reader_login(
        app_harness,
        admin.headers,
        name="自带凭据译者",
        capabilities=["library.read", "translation.use"],
    )
    other_reader, other_translator_headers = await create_reader_login(
        app_harness,
        admin.headers,
        name="另一位自带凭据译者",
        capabilities=["library.read", "translation.use"],
    )
    _, read_only_headers = await create_reader_login(
        app_harness,
        admin.headers,
        name="无翻译能力读者",
        capabilities=["library.read"],
    )
    denied_status = await client.get(
        "/api/v1/me/provider-credential",
        headers=read_only_headers,
    )
    assert denied_status.status_code == 403
    assert denied_status.json()["error"]["code"] == "library_capability_required"

    async with app_harness.session_factory() as session:
        recovery = await AdminService(session, app_harness.settings).create_recovery()
    recovery_login = await client.post(
        "/api/v1/auth/login",
        json={
            "credential": recovery.credential,
            "refresh_token_delivery": "body",
            "device": {
                "client_instance_id": str(uuid4()),
                "name": "受限恢复设备",
                "platform": "web",
                "app_version": "0.10.0-test",
            },
        },
    )
    assert recovery_login.status_code == 200, recovery_login.text
    recovery_denied = await client.get(
        "/api/v1/me/provider-credential",
        headers={"Authorization": f"Bearer {recovery_login.json()['access_token']}"},
    )
    assert recovery_denied.status_code == 403
    assert recovery_denied.json()["error"]["code"] == "recovery_session_restricted"
    initial_status = await client.get(
        "/api/v1/me/provider-credential",
        headers=translator_headers,
    )
    assert initial_status.status_code == 200
    assert initial_status.json()["configured"] is True
    assert initial_status.json()["provider"] == "openai_compatible"
    assert initial_status.json()["provider_name"] == "OpenAI"
    assert initial_status.json()["base_url"] == "https://api.openai.com/v1"
    assert initial_status.json()["model"] == "gpt-4.1-mini"
    assert initial_status.json()["thinking_enabled"] is False
    assert initial_status.json()["version"] == 1
    assert "api_key" not in initial_status.text
    unsupported_openai_thinking = await client.put(
        "/api/v1/me/provider-credential",
        headers=translator_headers,
        json={
            "provider": "openai_compatible",
            "model": "gpt-4.1-mini",
            "thinking_enabled": True,
            "api_key": "sk-must-not-be-stored",
        },
    )
    assert unsupported_openai_thinking.status_code == 422
    assert unsupported_openai_thinking.json()["error"]["code"] == "provider_thinking_not_supported"

    created = await create_txt_book(client, admin.headers, title="凭据版本测试书")
    first = await create_run(
        client,
        translator_headers,
        book_id=created["book"]["id"],
        source_edition_id=created["edition"]["id"],
    )
    assert first.status_code == 201, first.text
    first_run = first.json()
    assert first_run["configuration"]["credential_provider_name"] == "OpenAI"
    assert first_run["configuration"]["credential_base_url"] == "https://api.openai.com/v1"

    rotated = await client.put(
        "/api/v1/me/provider-credential",
        headers=translator_headers,
        json={
            "provider": "deepseek",
            "model": "deepseek-chat",
            "api_key": "sk-rotated-never-return-this-value",
        },
    )
    assert rotated.status_code == 200, rotated.text
    assert rotated.headers["Cache-Control"] == "no-store"
    assert rotated.json()["version"] == 2
    assert rotated.json()["provider"] == "deepseek"
    assert rotated.json()["provider_name"] == "DeepSeek"
    assert rotated.json()["base_url"] == "https://api.deepseek.com/v1"
    assert rotated.json()["model"] == "deepseek-chat"
    assert "sk-rotated" not in rotated.text
    other_status = await client.get(
        "/api/v1/me/provider-credential",
        headers=other_translator_headers,
    )
    assert other_status.status_code == 200
    assert other_status.json()["configured"] is True
    assert other_status.json()["version"] == 1

    second = await create_run(
        client,
        translator_headers,
        book_id=created["book"]["id"],
        source_edition_id=created["edition"]["id"],
    )
    assert second.status_code == 201, second.text
    assert second.json()["configuration"]["credential_provider_name"] == "DeepSeek"
    assert len(fake.credential_scopes) == 2
    assert fake.credential_scopes[0] != fake.credential_scopes[1]

    async with app_harness.session_factory() as session:
        versions = list(
            (
                await session.scalars(
                    select(ProviderCredentialVersionModel)
                    .where(ProviderCredentialVersionModel.user_id == UUID(reader["id"]))
                    .order_by(ProviderCredentialVersionModel.version)
                )
            ).all()
        )
        assert [item.version for item in versions] == [1, 2]
        assert versions[0].retired_at is not None and versions[0].revoked_at is None
        assert versions[1].retired_at is None and versions[1].revoked_at is None
        assert versions[1].ciphertext != b"sk-rotated-never-return-this-value"
        first_bound = await ProviderCredentialRepository(session).resolve_for_relay(
            UUID(fake.credential_scopes[0]),
            remote_job_id=first_run["remote_job_id"],
        )
        assert first_bound is not None and first_bound.version == 1
        stored_run = await session.get(
            EditionTranslationRunModel,
            UUID(first_run["id"]),
        )
        other_credential = await ProviderCredentialRepository(session).current(
            UUID(other_reader["id"])
        )
        assert stored_run is not None and other_credential is not None
        stored_run.status = "failed"
        await session.flush()
        assert (
            await ProviderCredentialRepository(session).resolve_for_relay(
                UUID(fake.credential_scopes[0]),
                remote_job_id=first_run["remote_job_id"],
            )
            is None
        )
        stored_run.status = "partially_succeeded"
        await session.flush()
        assert (
            await ProviderCredentialRepository(session).resolve_for_relay(
                UUID(fake.credential_scopes[0]),
                remote_job_id=first_run["remote_job_id"],
            )
            is None
        )
        stored_run.status = "queued"
        stored_run.provider_credential_version_id = other_credential.id
        await session.flush()
        assert (
            await ProviderCredentialRepository(session).resolve_for_relay(
                other_credential.id,
                remote_job_id=first_run["remote_job_id"],
            )
            is None
        )
        await session.rollback()

    kimi = await client.put(
        "/api/v1/me/provider-credential",
        headers=translator_headers,
        json={
            "provider": "kimi",
            "model": "kimi-k2.5",
            "api_key": "sk-kimi-never-return",
            "thinking_enabled": True,
        },
    )
    assert kimi.status_code == 200, kimi.text
    assert kimi.json()["version"] == 3
    assert kimi.json()["provider"] == "kimi"
    assert kimi.json()["provider_name"] == "Kimi"
    assert kimi.json()["base_url"] == "https://api.moonshot.cn/v1"
    assert kimi.json()["model"] == "kimi-k2.5"
    assert kimi.json()["thinking_enabled"] is True

    removed = await client.delete(
        "/api/v1/me/provider-credential",
        headers=translator_headers,
    )
    assert removed.status_code == 204
    missing = await client.get(
        "/api/v1/me/provider-credential",
        headers=translator_headers,
    )
    assert missing.status_code == 200
    assert missing.json()["configured"] is False
    assert missing.json()["version"] is None
    assert missing.json()["provider"] == "kimi"
    assert missing.json()["provider_name"] == "Kimi"
    assert missing.json()["base_url"] == "https://api.moonshot.cn/v1"
    assert missing.json()["model"] == "kimi-k2.5"
    assert missing.json()["thinking_enabled"] is False
    other_after_removal = await client.get(
        "/api/v1/me/provider-credential",
        headers=other_translator_headers,
    )
    assert other_after_removal.status_code == 200
    assert other_after_removal.json()["configured"] is True
    assert other_after_removal.json()["version"] == 1
    refused = await create_run(
        client,
        translator_headers,
        book_id=created["book"]["id"],
        source_edition_id=created["edition"]["id"],
        target_language="fr",
    )
    assert refused.status_code == 409
    assert refused.json()["error"]["code"] == "provider_credential_required"

    async with app_harness.session_factory() as session:
        versions = list(
            (
                await session.scalars(
                    select(ProviderCredentialVersionModel).where(
                        ProviderCredentialVersionModel.user_id == UUID(reader["id"])
                    )
                )
            ).all()
        )
        assert versions and all(item.revoked_at is not None for item in versions)
        assert (
            await ProviderCredentialRepository(session).resolve_for_relay(
                UUID(fake.credential_scopes[0]),
                remote_job_id=first_run["remote_job_id"],
            )
            is None
        )


@pytest.mark.integration
async def test_provider_relay_hardens_forwarding_and_persists_sanitized_usage(
    app_harness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeLinguaSpindle()
    configure_fake(app_harness, fake)
    admin = await app_harness.provision_admin()
    _, translator_headers = await create_reader_login(
        app_harness,
        admin.headers,
        name="中继测试译者",
        capabilities=["library.read", "translation.use"],
    )
    _, other_translator_headers = await create_reader_login(
        app_harness,
        admin.headers,
        name="中继隔离对照译者",
        capabilities=["library.read", "translation.use"],
    )
    unsupported_custom_thinking = await app_harness.client.put(
        "/api/v1/me/provider-credential",
        headers=translator_headers,
        json={
            "provider": "custom",
            "custom_name": "私有兼容服务",
            "base_url": "https://provider.example/v1",
            "model": "custom-model",
            "thinking_enabled": True,
            "api_key": "sk-must-not-be-stored",
        },
    )
    assert unsupported_custom_thinking.status_code == 422
    assert unsupported_custom_thinking.json()["error"]["code"] == "provider_thinking_not_supported"
    disallowed_custom = await app_harness.client.put(
        "/api/v1/me/provider-credential",
        headers=translator_headers,
        json={
            "provider": "custom",
            "custom_name": "未允许服务",
            "base_url": "https://attacker.example/v1",
            "model": "custom-model",
            "api_key": "sk-must-not-be-stored",
        },
    )
    assert disallowed_custom.status_code == 422
    assert disallowed_custom.json()["error"]["code"] == "provider_base_url_not_allowed"
    custom_configuration = await app_harness.client.put(
        "/api/v1/me/provider-credential",
        headers=translator_headers,
        json={
            "provider": "custom",
            "custom_name": "私有兼容服务",
            "base_url": "https://provider.example/v1/",
            "model": "custom-translation-model",
            "api_key": "sk-custom-never-return",
        },
    )
    assert custom_configuration.status_code == 200, custom_configuration.text
    assert custom_configuration.json()["provider"] == "custom"
    assert custom_configuration.json()["provider_name"] == "私有兼容服务"
    assert custom_configuration.json()["base_url"] == "https://provider.example/v1"
    assert custom_configuration.json()["model"] == "custom-translation-model"
    assert custom_configuration.json()["thinking_enabled"] is False
    assert "sk-custom" not in custom_configuration.text
    created = await create_txt_book(
        app_harness.client,
        admin.headers,
        title="中继边界测试书",
    )
    started = await create_run(
        app_harness.client,
        translator_headers,
        book_id=created["book"]["id"],
        source_edition_id=created["edition"]["id"],
    )
    assert started.status_code == 201, started.text
    run = started.json()
    assert run["configuration"]["credential_provider_name"] == "私有兼容服务"
    assert run["configuration"]["thinking_enabled"] is False
    credential_scope = fake.credential_scopes[0]
    bootstrap_started = await create_run(
        app_harness.client,
        translator_headers,
        book_id=created["book"]["id"],
        source_edition_id=created["edition"]["id"],
        target_language="fr",
    )
    assert bootstrap_started.status_code == 201, bootstrap_started.text
    bootstrap_run = bootstrap_started.json()
    assert fake.credential_scopes[1] == credential_scope
    async with app_harness.session_factory() as session:
        exact_stored = await session.get(
            EditionTranslationRunModel,
            UUID(run["id"]),
        )
        bootstrap_stored = await session.get(
            EditionTranslationRunModel,
            UUID(bootstrap_run["id"]),
        )
        assert exact_stored is not None
        assert bootstrap_stored is not None
        assert exact_stored.remote_job_id == run["remote_job_id"]
        bootstrap_stored.remote_job_id = None
        bootstrap_stored.status = "preparing"
        await session.commit()
    shared_secret = "relay-service-secret-" + ("x" * 32)
    relay_settings = ProviderRelaySettings(
        database_url=app_harness.settings.database_url,
        provider_credential_master_key=SecretStr(base64.b64encode(bytes(range(32))).decode()),
        provider_relay_service_secret=SecretStr(shared_secret),
        provider_relay_upstream_base_url="https://provider.example/v1",
        provider_relay_allowed_models=["gpt-4.1-mini"],
        provider_relay_custom_allowed_base_urls=["https://provider.example/v1"],
        provider_relay_max_request_bytes=512,
        provider_relay_max_response_bytes=4096,
    )
    monkeypatch.setattr(provider_relay_module, "settings", relay_settings)

    async def override_relay_session():
        async with app_harness.session_factory() as session:
            yield session

    provider_relay_app.dependency_overrides[get_relay_session] = override_relay_session
    relay_headers = {
        "Authorization": f"Bearer {shared_secret}",
        "X-LinguaSpindle-Credential-Scope": credential_scope,
        "X-LinguaSpindle-Job-ID": run["remote_job_id"],
    }
    request_payload = {
        "model": "gpt-4.1-mini",
        "messages": [
            {"role": "system", "content": "Translate."},
            {"role": "user", "content": "正文"},
        ],
        "temperature": 0,
    }
    upstream_requests: list[httpx.Request] = []

    def success_handler(request: httpx.Request) -> httpx.Response:
        upstream_requests.append(request)
        assert str(request.url) == "https://provider.example/v1/chat/completions"
        assert request.read()
        assert request.content
        assert b'"model":"custom-translation-model"' in request.content
        assert b'"thinking"' not in request.content
        assert request.headers["Authorization"] == "Bearer sk-custom-never-return"
        assert shared_secret not in request.headers["Authorization"]
        assert "X-LinguaSpindle-Credential-Scope" not in request.headers
        assert "X-LinguaSpindle-Job-ID" not in request.headers
        return httpx.Response(
            200,
            headers={"Content-Type": "application/json"},
            json={
                "id": "upstream-private-id",
                "model": "gpt-4.1-mini",
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": "Translated.",
                        },
                        "finish_reason": "stop",
                        "logprobs": {"must": "be stripped"},
                    }
                ],
                "usage": {
                    "prompt_tokens": 12,
                    "completion_tokens": 3,
                    "total_tokens": 15,
                    "private_detail": 99,
                },
                "system_fingerprint": "must-be-stripped",
            },
        )

    provider_relay_app.state.upstream_transport = httpx.MockTransport(success_handler)
    transport = httpx.ASGITransport(app=provider_relay_app)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://relay") as relay_client:
            assert (await relay_client.get("/health")).status_code == 200
            assert (
                await relay_client.post("/v1/chat/completions", json=request_payload)
            ).status_code == 401
            missing_job_headers = dict(relay_headers)
            missing_job_headers.pop("X-LinguaSpindle-Job-ID")
            assert (
                await relay_client.post(
                    "/v1/chat/completions",
                    headers=missing_job_headers,
                    json=request_payload,
                )
            ).status_code == 400
            assert (
                await relay_client.post(
                    "/v1/chat/completions",
                    headers=relay_headers,
                    json={**request_payload, "model": "unapproved-model"},
                )
            ).status_code == 403
            assert (
                await relay_client.post(
                    "/v1/chat/completions",
                    headers={**relay_headers, "Content-Type": "application/json"},
                    content=b'{"model":"' + (b"x" * 600) + b'"}',
                )
            ).status_code == 413

            successful = await relay_client.post(
                "/v1/chat/completions",
                headers=relay_headers,
                json=request_payload,
            )
            # PostgreSQL sorts NULL before TRUE for a descending boolean order.
            # The exact binding must still win over the unbound preparing row.
            assert successful.status_code == 200, successful.text
            assert successful.json() == {
                "model": "gpt-4.1-mini",
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": "Translated.",
                        },
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 12,
                    "completion_tokens": 3,
                    "total_tokens": 15,
                },
            }
            assert len(upstream_requests) == 1
            async with app_harness.session_factory() as session:
                claimed_run = await session.get(
                    EditionTranslationRunModel,
                    UUID(run["id"]),
                )
                assert claimed_run is not None
                assert claimed_run.remote_job_id == run["remote_job_id"]
                unclaimed_bootstrap = await session.get(
                    EditionTranslationRunModel,
                    UUID(bootstrap_run["id"]),
                )
                assert unclaimed_bootstrap is not None
                assert unclaimed_bootstrap.remote_job_id is None

            redirect_requests: list[httpx.Request] = []

            def redirect_handler(request: httpx.Request) -> httpx.Response:
                redirect_requests.append(request)
                return httpx.Response(
                    307,
                    headers={"Location": "https://attacker.example/steal"},
                )

            provider_relay_app.state.upstream_transport = httpx.MockTransport(redirect_handler)
            redirected = await relay_client.post(
                "/v1/chat/completions",
                headers=relay_headers,
                json=request_payload,
            )
            assert redirected.status_code == 502
            assert len(redirect_requests) == 1

            provider_relay_app.state.upstream_transport = httpx.MockTransport(
                lambda request: httpx.Response(
                    400,
                    headers={"Content-Type": "application/json"},
                    json={
                        "error": {
                            "message": "secret upstream body",
                            "api_key": "sk-do-not-return",
                        }
                    },
                )
            )
            rejected = await relay_client.post(
                "/v1/chat/completions",
                headers=relay_headers,
                json=request_payload,
            )
            assert rejected.status_code == 502
            assert "secret upstream body" not in rejected.text
            assert "sk-do-not-return" not in rejected.text

            reflected_keys: list[str] = []

            def reflected_key_handler(request: httpx.Request) -> httpx.Response:
                provider_key = request.headers["Authorization"].removeprefix("Bearer ")
                reflected_keys.append(provider_key)
                return httpx.Response(
                    200,
                    headers={"Content-Type": "application/json"},
                    json={
                        "model": "gpt-4.1-mini",
                        "choices": [
                            {
                                "message": {
                                    "role": "assistant",
                                    "content": f"reflected credential: {provider_key}",
                                }
                            }
                        ],
                    },
                )

            provider_relay_app.state.upstream_transport = httpx.MockTransport(reflected_key_handler)
            reflected = await relay_client.post(
                "/v1/chat/completions",
                headers={
                    **relay_headers,
                    "X-LinguaSpindle-Job-ID": bootstrap_run["remote_job_id"],
                },
                json=request_payload,
            )
            assert reflected.status_code == 502
            assert reflected_keys
            assert reflected_keys[0] not in reflected.text
            async with app_harness.session_factory() as session:
                claimed_bootstrap = await session.get(
                    EditionTranslationRunModel,
                    UUID(bootstrap_run["id"]),
                )
                assert claimed_bootstrap is not None
                assert claimed_bootstrap.remote_job_id == bootstrap_run["remote_job_id"]
    finally:
        provider_relay_app.dependency_overrides.clear()
        provider_relay_app.state.upstream_transport = None

    async with app_harness.session_factory() as session:
        usage = list((await session.scalars(select(ProviderUsageRecordModel))).all())
        assert len(usage) == 1
        assert usage[0].prompt_tokens == 12
        assert usage[0].completion_tokens == 3
        assert usage[0].total_tokens == 15
        assert usage[0].model == "custom-translation-model"
        assert usage[0].remote_job_id == run["remote_job_id"]

    status_response = await app_harness.client.get(
        "/api/v1/me/provider-credential",
        headers=translator_headers,
    )
    assert status_response.status_code == 200
    assert status_response.json()["provider"] == "custom"
    assert status_response.json()["provider_name"] == "私有兼容服务"
    assert status_response.json()["usage"]["all_time"] == {
        "request_count": 1,
        "prompt_tokens": 12,
        "completion_tokens": 3,
        "total_tokens": 15,
    }
    other_status = await app_harness.client.get(
        "/api/v1/me/provider-credential",
        headers=other_translator_headers,
    )
    assert other_status.status_code == 200
    assert other_status.json()["usage"]["all_time"] == {
        "request_count": 0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
    }


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
    assert len(fake.credential_scopes) == 1
    assert run["configuration"]["credential_version"] == 1
    assert "credential_scope" not in run["configuration"]
    async with app_harness.session_factory() as session:
        stored_run = await session.get(EditionTranslationRunModel, UUID(run["id"]))
        assert stored_run is not None
        assert str(stored_run.provider_credential_version_id) == fake.credential_scopes[0]

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

    observed_control_statuses: list[str] = []

    async def observe_control_status(job_id: str, action: str) -> None:
        assert job_id == run["remote_job_id"]
        assert action == "retry"
        async with app_harness.session_factory() as session:
            stored = await session.get(EditionTranslationRunModel, UUID(run["id"]))
            assert stored is not None
            observed_control_statuses.append(str(stored.status))

    fake.before_control = observe_control_status
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
    assert observed_control_statuses == ["preparing"]

    fake.set_status(run["remote_job_id"], "failed")
    failed_again = await client.post(
        f"/api/v1/translation-runs/{run['id']}/sync",
        headers=translator_headers,
    )
    assert failed_again.status_code == 200
    assert failed_again.json()["status"] == "failed"
    fake.control_failure = LinguaSpindleFailure(
        "linguaspindle_control_rejected",
        "远端明确拒绝了重试。",
        status_code=503,
        retryable=True,
    )
    rejected_retry = await client.post(
        f"/api/v1/translation-runs/{run['id']}/retry",
        headers=translator_headers,
    )
    assert rejected_retry.status_code == 503
    assert rejected_retry.json()["error"]["code"] == "linguaspindle_control_rejected"
    async with app_harness.session_factory() as session:
        stored = await session.get(EditionTranslationRunModel, UUID(run["id"]))
        assert stored is not None
        assert str(stored.status) == "failed"
        assert stored.completed_at is not None


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
