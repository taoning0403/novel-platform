from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any, BinaryIO, Protocol
from urllib.parse import urlsplit
from uuid import UUID

import httpx

from novel_platform.config import Settings
from novel_platform.domain.library.models import FileFormat

_SAFE_ID = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
_MAX_JSON_BYTES = 2 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class LinguaTranslationFormat:
    source_format: FileFormat
    pipeline_key: str
    source_media_type: str
    artifact_kind: str
    artifact_media_type: str
    extension: str
    label: str


_TRANSLATION_FORMATS = {
    FileFormat.TXT: LinguaTranslationFormat(
        source_format=FileFormat.TXT,
        pipeline_key="novel_txt_v1",
        source_media_type="text/plain",
        artifact_kind="novel_export_txt",
        artifact_media_type="text/plain",
        extension=".txt",
        label="TXT",
    ),
    FileFormat.EPUB: LinguaTranslationFormat(
        source_format=FileFormat.EPUB,
        pipeline_key="novel_epub_v1",
        source_media_type="application/epub+zip",
        artifact_kind="novel_export_epub",
        artifact_media_type="application/epub+zip",
        extension=".epub",
        label="EPUB",
    ),
}


def translation_format_contract(source_format: FileFormat) -> LinguaTranslationFormat:
    try:
        return _TRANSLATION_FORMATS[source_format]
    except KeyError as exc:
        raise ValueError("unsupported novel translation source format") from exc


@dataclass(frozen=True, slots=True)
class LinguaServiceStatus:
    enabled: bool
    available: bool
    version: str | None
    source_format: FileFormat
    pipeline_key: str
    pipeline_version: str | None
    provider_id: str
    provider_name: str | None
    provider_model: str | None
    provider_offline: bool
    idempotency_required: bool | None
    error_code: str | None = None
    error_message: str | None = None


@dataclass(frozen=True, slots=True)
class RemoteProject:
    id: str
    request_id: str | None


@dataclass(frozen=True, slots=True)
class RemoteJob:
    id: str
    project_id: str
    status: str
    progress: float
    request_id: str | None
    error_code: str | None = None


@dataclass(frozen=True, slots=True)
class RemoteArtifact:
    id: str
    project_id: str
    job_id: str | None
    kind: str
    filename: str
    media_type: str
    size: int
    checksum: str
    download_url: str


@dataclass(frozen=True, slots=True)
class DownloadedArtifact:
    size: int
    sha256: str


class LinguaSpindleFailure(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int = 503,
        ambiguous: bool = False,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.ambiguous = ambiguous
        self.retryable = retryable


class LinguaSpindleGateway(Protocol):
    async def service_status(
        self,
        *,
        source_format: FileFormat,
        request_id: str,
    ) -> LinguaServiceStatus: ...

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
    ) -> RemoteProject: ...

    async def create_job(
        self,
        *,
        project_id: str,
        source_format: FileFormat,
        credential_scope: str,
        idempotency_key: str,
        request_id: str,
    ) -> RemoteJob: ...

    async def get_job(self, job_id: str, *, request_id: str) -> RemoteJob: ...

    async def control_job(
        self,
        job_id: str,
        action: str,
        *,
        request_id: str,
        idempotency_key: str | None = None,
    ) -> RemoteJob: ...

    async def list_artifacts(
        self,
        project_id: str,
        job_id: str,
        *,
        request_id: str,
    ) -> list[RemoteArtifact]: ...

    async def download_artifact(
        self,
        artifact: RemoteArtifact,
        destination: BinaryIO,
        *,
        request_id: str,
        max_bytes: int,
    ) -> DownloadedArtifact: ...

    async def delete_project(self, project_id: str, *, request_id: str) -> None: ...


class LinguaSpindleClient:
    def __init__(
        self,
        settings: Settings,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.settings = settings
        self.base_url = settings.linguaspindle_base_url
        self.transport = transport
        self.timeout = httpx.Timeout(
            connect=settings.linguaspindle_connect_timeout_seconds,
            read=settings.linguaspindle_read_timeout_seconds,
            write=settings.linguaspindle_read_timeout_seconds,
            pool=settings.linguaspindle_connect_timeout_seconds,
        )

    async def service_status(
        self,
        *,
        source_format: FileFormat,
        request_id: str,
    ) -> LinguaServiceStatus:
        provider_id = self.settings.linguaspindle_provider_id
        format_contract = translation_format_contract(source_format)
        if not self.settings.linguaspindle_enabled:
            return LinguaServiceStatus(
                enabled=False,
                available=False,
                version=None,
                source_format=source_format,
                pipeline_key=format_contract.pipeline_key,
                pipeline_version=None,
                provider_id=provider_id,
                provider_name=None,
                provider_model=None,
                provider_offline=False,
                idempotency_required=None,
                error_code="feature_disabled",
                error_message="小说翻译服务未启用。",
            )
        try:
            await self._require_relay_health(request_id=request_id)
            health, _ = await self._json("GET", "/health", request_id=request_id)
            system, _ = await self._json("GET", "/api/system", request_id=request_id)
            pipelines, _ = await self._json("GET", "/api/pipelines", request_id=request_id)
            providers, _ = await self._json("GET", "/api/providers", request_id=request_id)
            version = _string(health, "version")
            if _string(health, "status") != "ok" or _string(health, "database") != "ok":
                raise LinguaSpindleFailure(
                    "translation_service_unhealthy", "小说翻译服务暂不可用。"
                )
            if not _supported_version(version):
                raise LinguaSpindleFailure(
                    "translation_service_incompatible", "小说翻译服务版本不兼容。"
                )
            if not isinstance(system, dict) or system.get("require_idempotency_key") is not True:
                raise LinguaSpindleFailure(
                    "translation_idempotency_not_required", "小说翻译服务未启用强制幂等。"
                )
            pipeline = _find_mapping(pipelines, "key", format_contract.pipeline_key)
            provider = _find_mapping(providers, "id", provider_id)
            if pipeline is None:
                raise LinguaSpindleFailure(
                    "translation_pipeline_unavailable",
                    f"小说 {format_contract.label} 翻译管线不可用。",
                )
            if provider is None or provider.get("configured") is not True:
                raise LinguaSpindleFailure(
                    "translation_provider_unconfigured", "小说翻译 Provider 尚未配置。"
                )
            return LinguaServiceStatus(
                enabled=True,
                available=True,
                version=version,
                source_format=source_format,
                pipeline_key=format_contract.pipeline_key,
                pipeline_version=_optional_string(pipeline.get("version")),
                provider_id=provider_id,
                provider_name=_optional_string(provider.get("display_name")),
                provider_model=_optional_string(provider.get("model")),
                provider_offline=provider.get("offline") is True,
                idempotency_required=True,
            )
        except LinguaSpindleFailure as exc:
            return LinguaServiceStatus(
                enabled=True,
                available=False,
                version=None,
                source_format=source_format,
                pipeline_key=format_contract.pipeline_key,
                pipeline_version=None,
                provider_id=provider_id,
                provider_name=None,
                provider_model=None,
                provider_offline=False,
                idempotency_required=None,
                error_code=exc.code,
                error_message=exc.message,
            )

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
        format_contract = translation_format_contract(source_format)
        payload, response = await self._json(
            "POST",
            "/api/projects",
            request_id=request_id,
            idempotency_key=idempotency_key,
            data={
                "name": f"Novel Platform translation {request_id}",
                "kind": "novel",
                "source_language": source_language,
                "target_language": target_language,
            },
            files={"source": (filename, source, format_contract.source_media_type)},
            ambiguous=True,
        )
        return RemoteProject(
            id=_remote_id(payload, "id"),
            request_id=_safe_header(response.headers.get("X-Request-ID")),
        )

    async def create_job(
        self,
        *,
        project_id: str,
        source_format: FileFormat,
        credential_scope: str,
        idempotency_key: str,
        request_id: str,
    ) -> RemoteJob:
        _validate_remote_id(project_id)
        format_contract = translation_format_contract(source_format)
        try:
            normalized_credential_scope = str(UUID(credential_scope))
        except ValueError as exc:
            raise ValueError("credential_scope must be a UUID") from exc
        if normalized_credential_scope != credential_scope:
            raise ValueError("credential_scope must use canonical UUID serialization")
        body = {
            "pipeline_key": format_contract.pipeline_key,
            "profile_id": self.settings.linguaspindle_profile_id,
            "provider_id": self.settings.linguaspindle_provider_id,
            "adapter_id": None,
            "credential_scope": credential_scope,
        }
        payload, response = await self._json(
            "POST",
            f"/api/projects/{project_id}/jobs",
            request_id=request_id,
            idempotency_key=idempotency_key,
            json=body,
            ambiguous=True,
        )
        return _remote_job(payload, response)

    async def get_job(self, job_id: str, *, request_id: str) -> RemoteJob:
        _validate_remote_id(job_id)
        payload, response = await self._json("GET", f"/api/jobs/{job_id}", request_id=request_id)
        return _remote_job(payload, response)

    async def control_job(
        self,
        job_id: str,
        action: str,
        *,
        request_id: str,
        idempotency_key: str | None = None,
    ) -> RemoteJob:
        _validate_remote_id(job_id)
        if action not in {"pause", "resume", "cancel", "retry"}:
            raise ValueError("unsupported LinguaSpindle control")
        payload, response = await self._json(
            "POST",
            f"/api/jobs/{job_id}/{action}",
            request_id=request_id,
            idempotency_key=idempotency_key,
            ambiguous=True,
        )
        return _remote_job(payload, response)

    async def list_artifacts(
        self,
        project_id: str,
        job_id: str,
        *,
        request_id: str,
    ) -> list[RemoteArtifact]:
        _validate_remote_id(project_id)
        _validate_remote_id(job_id)
        payload, _ = await self._json(
            "GET",
            f"/api/projects/{project_id}/artifacts",
            request_id=request_id,
            params={"job_id": job_id},
        )
        if not isinstance(payload, list):
            raise _protocol_failure()
        return [_remote_artifact(item) for item in payload]

    async def download_artifact(
        self,
        artifact: RemoteArtifact,
        destination: BinaryIO,
        *,
        request_id: str,
        max_bytes: int,
    ) -> DownloadedArtifact:
        path = self._artifact_download_path(artifact)
        headers = {"X-Request-ID": request_id}
        size = 0
        digest = hashlib.sha256()
        try:
            async with self._client() as client:
                async with client.stream("GET", path, headers=headers) as response:
                    if 300 <= response.status_code < 400:
                        raise _protocol_failure()
                    if response.status_code >= 400:
                        await response.aread()
                        raise self._response_failure(response)
                    content_length = _content_length(response.headers)
                    if content_length is not None and content_length > max_bytes:
                        raise LinguaSpindleFailure(
                            "translation_artifact_too_large",
                            "翻译产物超过本地导入上限。",
                            status_code=413,
                        )
                    async for chunk in response.aiter_bytes():
                        size += len(chunk)
                        if size > max_bytes:
                            raise LinguaSpindleFailure(
                                "translation_artifact_too_large",
                                "翻译产物超过本地导入上限。",
                                status_code=413,
                            )
                        destination.write(chunk)
                        digest.update(chunk)
        except LinguaSpindleFailure:
            raise
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            raise LinguaSpindleFailure(
                "translation_service_unavailable",
                "小说翻译服务暂不可用。",
                ambiguous=False,
                retryable=True,
            ) from exc
        return DownloadedArtifact(size=size, sha256=digest.hexdigest())

    async def delete_project(self, project_id: str, *, request_id: str) -> None:
        _validate_remote_id(project_id)
        await self._json(
            "DELETE",
            f"/api/projects/{project_id}",
            request_id=request_id,
            params={"confirmed": "true"},
            ambiguous=True,
            allow_empty=True,
        )

    async def _require_relay_health(self, *, request_id: str) -> None:
        try:
            payload, _ = await self._json(
                "GET",
                "/health",
                request_id=request_id,
                client_base_url=self.settings.provider_relay_internal_url,
            )
            if not isinstance(payload, dict) or payload.get("status") != "ok":
                raise _protocol_failure()
        except LinguaSpindleFailure as exc:
            raise LinguaSpindleFailure(
                "provider_relay_unavailable",
                "模型服务凭据中继暂不可用。",
                retryable=True,
            ) from exc

    def _client(self, base_url: str | None = None) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=base_url or self.base_url,
            timeout=self.timeout,
            follow_redirects=False,
            transport=self.transport,
        )

    async def _json(
        self,
        method: str,
        path: str,
        *,
        request_id: str,
        idempotency_key: str | None = None,
        ambiguous: bool = False,
        allow_empty: bool = False,
        client_base_url: str | None = None,
        **kwargs: Any,
    ) -> tuple[object, httpx.Response]:
        headers = {"X-Request-ID": request_id, "Accept": "application/json"}
        if idempotency_key is not None:
            headers["Idempotency-Key"] = idempotency_key
        try:
            async with self._client(client_base_url) as client:
                async with client.stream(method, path, headers=headers, **kwargs) as streamed:
                    if 300 <= streamed.status_code < 400:
                        raise _protocol_failure()
                    declared_length = _content_length(streamed.headers)
                    if declared_length is not None and declared_length > _MAX_JSON_BYTES:
                        raise _protocol_failure()
                    body = bytearray()
                    async for chunk in streamed.aiter_bytes():
                        body.extend(chunk)
                        if len(body) > _MAX_JSON_BYTES:
                            raise _protocol_failure()
                    response = httpx.Response(
                        streamed.status_code,
                        headers=streamed.headers,
                        content=bytes(body),
                        request=streamed.request,
                    )
        except LinguaSpindleFailure:
            raise
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            raise LinguaSpindleFailure(
                "translation_service_unavailable",
                "小说翻译服务暂不可用。",
                ambiguous=ambiguous,
                retryable=True,
            ) from exc
        if response.status_code >= 400:
            failure = self._response_failure(response)
            failure.ambiguous = ambiguous and response.status_code >= 500
            raise failure
        if not response.content and allow_empty:
            return None, response
        try:
            return response.json(), response
        except ValueError as exc:
            raise _protocol_failure() from exc

    @staticmethod
    def _response_failure(response: httpx.Response) -> LinguaSpindleFailure:
        remote_code = "translation_remote_error"
        retryable = response.status_code in {429, 500, 502, 503, 504}
        if len(response.content) <= _MAX_JSON_BYTES:
            try:
                payload = response.json()
            except ValueError:
                payload = None
            if isinstance(payload, dict) and isinstance(payload.get("error"), dict):
                candidate = payload["error"].get("code")
                if isinstance(candidate, str) and _SAFE_ID.fullmatch(candidate):
                    remote_code = f"linguaspindle_{candidate.lower()}"
                retryable = payload["error"].get("retryable") is True or retryable
        status_code = 503 if response.status_code >= 500 else response.status_code
        return LinguaSpindleFailure(
            remote_code,
            "小说翻译服务拒绝了该操作。",
            status_code=status_code,
            retryable=retryable,
        )

    def _artifact_download_path(self, artifact: RemoteArtifact) -> str:
        _validate_remote_id(artifact.id)
        parsed = urlsplit(artifact.download_url)
        expected = f"/api/artifacts/{artifact.id}/download"
        if parsed.scheme or parsed.netloc:
            base = urlsplit(self.base_url)
            if (parsed.scheme, parsed.hostname, parsed.port) != (
                base.scheme,
                base.hostname,
                base.port,
            ):
                raise _protocol_failure()
        if parsed.path != expected or parsed.query or parsed.fragment:
            raise _protocol_failure()
        return expected


def _remote_job(payload: object, response: httpx.Response) -> RemoteJob:
    if not isinstance(payload, dict):
        raise _protocol_failure()
    status = _string(payload, "status")
    if status not in {
        "queued",
        "running",
        "paused",
        "cancelling",
        "cancelled",
        "succeeded",
        "failed",
        "partially_succeeded",
    }:
        raise _protocol_failure()
    progress = payload.get("progress")
    if (
        not isinstance(progress, (int, float))
        or isinstance(progress, bool)
        or not 0 <= progress <= 1
    ):
        raise _protocol_failure()
    error_code: str | None = None
    error = payload.get("error")
    if isinstance(error, dict):
        candidate = error.get("code")
        if isinstance(candidate, str) and _SAFE_ID.fullmatch(candidate):
            error_code = candidate.lower()
    return RemoteJob(
        id=_remote_id(payload, "id"),
        project_id=_remote_id(payload, "project_id"),
        status=status,
        progress=float(progress),
        request_id=_safe_header(response.headers.get("X-Request-ID")),
        error_code=error_code,
    )


def _remote_artifact(payload: object) -> RemoteArtifact:
    if not isinstance(payload, dict):
        raise _protocol_failure()
    size = payload.get("size")
    if not isinstance(size, int) or isinstance(size, bool) or size < 0:
        raise _protocol_failure()
    checksum = _string(payload, "checksum")
    if not re.fullmatch(r"[0-9a-f]{64}", checksum):
        raise _protocol_failure()
    job_id_value = payload.get("job_id")
    job_id = None if job_id_value is None else _validate_remote_id_value(job_id_value)
    return RemoteArtifact(
        id=_remote_id(payload, "id"),
        project_id=_remote_id(payload, "project_id"),
        job_id=job_id,
        kind=_string(payload, "kind"),
        filename=_string(payload, "filename"),
        media_type=_string(payload, "media_type"),
        size=size,
        checksum=checksum,
        download_url=_string(payload, "download_url"),
    )


def _supported_version(value: str) -> bool:
    match = re.fullmatch(
        r"(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
        r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?",
        value,
    )
    if match is None:
        return False
    version = tuple(int(part) for part in match.groups())
    return (0, 3, 2) <= version < (0, 4, 0)


def _find_mapping(payload: object, key: str, value: str) -> dict[str, object] | None:
    if not isinstance(payload, list):
        raise _protocol_failure()
    for item in payload:
        if isinstance(item, dict) and item.get(key) == value:
            return item
    return None


def _string(payload: object, key: str) -> str:
    if not isinstance(payload, dict):
        raise _protocol_failure()
    value = payload.get(key)
    if not isinstance(value, str):
        raise _protocol_failure()
    return value


def _optional_string(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _remote_id(payload: object, key: str) -> str:
    return _validate_remote_id_value(_string(payload, key))


def _validate_remote_id_value(value: object) -> str:
    if not isinstance(value, str):
        raise _protocol_failure()
    _validate_remote_id(value)
    return value


def _validate_remote_id(value: str) -> None:
    if not _SAFE_ID.fullmatch(value):
        raise _protocol_failure()


def _safe_header(value: str | None) -> str | None:
    return value if value is not None and _SAFE_ID.fullmatch(value) else None


def _content_length(headers: httpx.Headers) -> int | None:
    raw = headers.get("Content-Length")
    if raw is None:
        return None
    try:
        value = int(raw)
    except ValueError as exc:
        raise _protocol_failure() from exc
    if value < 0:
        raise _protocol_failure()
    return value


def _protocol_failure() -> LinguaSpindleFailure:
    return LinguaSpindleFailure(
        "translation_protocol_error",
        "小说翻译服务返回了不兼容的响应。",
        status_code=502,
    )
