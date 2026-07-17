from collections.abc import Iterator
from typing import BinaryIO

from fastapi.responses import StreamingResponse

from novel_platform.application.library.filenames import content_disposition
from novel_platform.application.library.storage import FileStorage
from novel_platform.infrastructure.database.models import StoredFileModel

_CHUNK_SIZE = 1024 * 1024


def stored_file_response(
    storage: FileStorage,
    stored_file: StoredFileModel,
    *,
    attachment: bool,
) -> StreamingResponse:
    source = storage.open_file(stored_file.storage_key)
    headers = {
        "Content-Length": str(stored_file.size_bytes),
        "Cache-Control": "private, no-store",
        "X-Content-Type-Options": "nosniff",
    }
    if attachment:
        headers["Content-Disposition"] = content_disposition(stored_file.original_filename)
    return StreamingResponse(
        _stream(source),
        media_type=stored_file.media_type,
        headers=headers,
    )


def temporary_file_response(
    storage: FileStorage,
    temporary_key: str,
    *,
    media_type: str,
) -> StreamingResponse:
    source = storage.open_temporary(temporary_key)
    return StreamingResponse(
        _stream(source),
        media_type=media_type,
        headers={
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


def _stream(source: BinaryIO) -> Iterator[bytes]:
    try:
        while chunk := source.read(_CHUNK_SIZE):
            yield chunk
    finally:
        source.close()
