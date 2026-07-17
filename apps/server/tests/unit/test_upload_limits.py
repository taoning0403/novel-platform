from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError
from starlette.types import Receive, Scope, Send

from novel_platform.api.middleware.upload_limits import UploadBodyLimitMiddleware
from novel_platform.config import Settings


async def consume_body(scope: Scope, receive: Receive, send: Send) -> None:
    assert scope["type"] == "http"
    while True:
        message = await receive()
        if message["type"] != "http.request" or not message.get("more_body", False):
            break
    await send({"type": "http.response.start", "status": 204, "headers": []})
    await send({"type": "http.response.body", "body": b""})


@pytest.mark.asyncio
async def test_upload_limit_rejects_content_length_before_consuming_body() -> None:
    app = UploadBodyLimitMiddleware(consume_body, max_file_bytes=3)
    transport = httpx.ASGITransport(app=app)
    oversized = b"x" * (1024 * 1024 + 4)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/api/v1/imports/inspect", content=oversized)
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "upload_too_large"


@pytest.mark.asyncio
async def test_upload_limit_counts_chunked_bodies_without_content_length() -> None:
    app = UploadBodyLimitMiddleware(consume_body, max_file_bytes=3)
    body_size = 1024 * 1024 + 4

    async def chunks() -> AsyncIterator[bytes]:
        yield b"x" * (body_size // 2)
        yield b"x" * (body_size - body_size // 2)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/api/v1/imports/inspect", content=chunks())
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "upload_too_large"


@pytest.mark.parametrize("storage_root", [Path("relative/library"), Path("/")])
def test_library_storage_root_must_be_absolute_and_not_the_filesystem_root(
    storage_root: Path,
) -> None:
    with pytest.raises(ValidationError):
        Settings(library_storage_root=storage_root)


def test_epub_uncompressed_limit_cannot_be_smaller_than_upload_limit() -> None:
    with pytest.raises(ValidationError):
        Settings(
            max_upload_bytes=2,
            max_epub_uncompressed_bytes=1,
        )
