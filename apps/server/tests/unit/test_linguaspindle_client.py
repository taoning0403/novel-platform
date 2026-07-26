import io
from collections.abc import Callable
from dataclasses import replace

import httpx
import pytest
from pydantic import ValidationError

from novel_platform.config import Settings
from novel_platform.infrastructure.integrations.linguaspindle import (
    LinguaSpindleClient,
    LinguaSpindleFailure,
    RemoteArtifact,
)


def client_with(
    handler: Callable[[httpx.Request], httpx.Response],
    **settings_overrides: object,
) -> LinguaSpindleClient:
    settings = Settings(
        linguaspindle_enabled=True,
        linguaspindle_provider_id="mock",
    )
    settings = settings.model_copy(update=settings_overrides)
    return LinguaSpindleClient(settings, transport=httpx.MockTransport(handler))


def status_handler(request: httpx.Request, *, version: str = "0.3.2") -> httpx.Response:
    payloads = {
        "/health": {"status": "ok", "version": version, "database": "ok"},
        "/api/system": {"require_idempotency_key": True},
        "/api/pipelines": [{"key": "novel_txt_v1", "version": "1"}],
        "/api/providers": [
            {
                "id": "mock",
                "display_name": "Mock Provider",
                "configured": True,
                "model": "mock-v1",
                "offline": True,
            }
        ],
    }
    return httpx.Response(200, json=payloads[request.url.path])


def test_download_limit_is_fail_closed_only_when_translation_is_enabled() -> None:
    disabled = Settings(
        max_upload_bytes=1024,
        linguaspindle_enabled=False,
        linguaspindle_max_download_bytes=2048,
    )
    assert disabled.linguaspindle_enabled is False

    with pytest.raises(ValidationError, match="cannot exceed MAX_UPLOAD_BYTES"):
        Settings(
            max_upload_bytes=1024,
            linguaspindle_enabled=True,
            linguaspindle_max_download_bytes=2048,
        )


@pytest.mark.asyncio
async def test_status_requires_compatible_version_pipeline_provider_and_idempotency() -> None:
    client = client_with(status_handler)
    status = await client.service_status(request_id="np-status-test")
    assert status.available is True
    assert status.version == "0.3.2"
    assert status.pipeline_key == "novel_txt_v1"
    assert status.provider_id == "mock"
    assert status.provider_offline is True

    incompatible = client_with(lambda request: status_handler(request, version="0.4.0"))
    unavailable = await incompatible.service_status(request_id="np-status-test")
    assert unavailable.available is False
    assert unavailable.error_code == "translation_service_incompatible"

    prerelease = client_with(lambda request: status_handler(request, version="0.3.2-rc1"))
    prerelease_status = await prerelease.service_status(request_id="np-status-test")
    assert prerelease_status.available is False
    assert prerelease_status.error_code == "translation_service_incompatible"

    build_metadata = client_with(
        lambda request: status_handler(request, version="0.3.2+reviewed.1")
    )
    build_metadata_status = await build_metadata.service_status(request_id="np-status-test")
    assert build_metadata_status.available is True


@pytest.mark.asyncio
async def test_create_uses_deterministic_headers_and_never_follows_redirects() -> None:
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["idempotency"] = request.headers["Idempotency-Key"]
        captured["request_id"] = request.headers["X-Request-ID"]
        captured["content_type"] = request.headers["Content-Type"]
        return httpx.Response(
            201,
            headers={"X-Request-ID": "remote-request-1"},
            json={"id": "project-1"},
        )

    client = client_with(handler)
    project = await client.create_project(
        source=io.BytesIO("第一章\n正文".encode()),
        filename="source-r1.txt",
        source_language="zh-CN",
        target_language="en",
        idempotency_key="np:00000000-0000-4000-8000-000000000001:project:v1",
        request_id="np-00000000-0000-4000-8000-000000000001",
    )
    assert project.id == "project-1"
    assert project.request_id == "remote-request-1"
    assert captured["idempotency"].endswith(":project:v1")
    assert captured["request_id"].startswith("np-")
    assert captured["content_type"].startswith("multipart/form-data;")


@pytest.mark.asyncio
async def test_download_rejects_cross_origin_and_enforces_streaming_limit() -> None:
    artifact = RemoteArtifact(
        id="artifact-1",
        project_id="project-1",
        job_id="job-1",
        kind="novel_export_txt",
        filename="translated.txt",
        media_type="text/plain",
        size=8,
        checksum="0" * 64,
        download_url="https://attacker.example/api/artifacts/artifact-1/download",
    )
    client = client_with(lambda request: httpx.Response(200, content=b"12345678"))
    with pytest.raises(LinguaSpindleFailure) as cross_origin:
        await client.download_artifact(
            artifact,
            io.BytesIO(),
            request_id="np-download-1",
            max_bytes=16,
        )
    assert cross_origin.value.code == "translation_protocol_error"

    local = replace(
        artifact,
        download_url="/api/artifacts/artifact-1/download",
    )
    with pytest.raises(LinguaSpindleFailure) as too_large:
        await client.download_artifact(
            local,
            io.BytesIO(),
            request_id="np-download-1",
            max_bytes=4,
        )
    assert too_large.value.code == "translation_artifact_too_large"


@pytest.mark.asyncio
async def test_remote_error_message_and_details_are_not_propagated() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            502,
            json={
                "error": {
                    "code": "MODEL_API_ERROR",
                    "message": "secret provider body",
                    "details": {"api_key": "sk-do-not-leak"},
                    "retryable": True,
                }
            },
        )

    client = client_with(handler)
    with pytest.raises(LinguaSpindleFailure) as failure:
        await client.get_job("job-1", request_id="np-job-1")
    rendered = f"{failure.value.code} {failure.value.message}"
    assert failure.value.code == "linguaspindle_model_api_error"
    assert failure.value.retryable is True
    assert "secret provider body" not in rendered
    assert "sk-do-not-leak" not in rendered


@pytest.mark.asyncio
async def test_delete_accepts_a_no_content_success_response() -> None:
    client = client_with(lambda request: httpx.Response(204))
    await client.delete_project("project-1", request_id="np-cleanup-1")
