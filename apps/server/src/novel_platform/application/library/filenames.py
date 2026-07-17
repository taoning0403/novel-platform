import re
import unicodedata
from pathlib import PurePosixPath
from urllib.parse import quote

_CONTROL_PATTERN = re.compile(r"[\x00-\x1f\x7f]")


def sanitize_filename(filename: str | None, *, fallback: str = "upload") -> str:
    candidate = unicodedata.normalize("NFC", filename or "")
    candidate = candidate.replace("\\", "/")
    candidate = PurePosixPath(candidate).name
    visible_candidate = _CONTROL_PATTERN.sub("", candidate).strip().strip(".")
    candidate = _CONTROL_PATTERN.sub("_", candidate).strip().strip(".")
    if not visible_candidate:
        candidate = fallback
    if len(candidate) > 240:
        suffix = PurePosixPath(candidate).suffix[:20]
        stem_limit = max(1, 240 - len(suffix))
        candidate = f"{candidate[:stem_limit]}{suffix}"
    return candidate


def content_disposition(filename: str) -> str:
    safe = sanitize_filename(filename, fallback="download")
    ascii_fallback = safe.encode("ascii", "ignore").decode("ascii") or "download"
    ascii_fallback = ascii_fallback.replace('"', "_").replace("\\", "_")
    return f"attachment; filename=\"{ascii_fallback}\"; filename*=UTF-8''{quote(safe)}"
