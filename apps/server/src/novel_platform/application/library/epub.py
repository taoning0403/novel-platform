import io
import posixpath
import stat
import warnings
import zipfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import cast
from urllib.parse import unquote, urlsplit
from xml.etree.ElementTree import Element, ParseError

from defusedxml.common import DefusedXmlException  # type: ignore[import-untyped]
from defusedxml.ElementTree import fromstring  # type: ignore[import-untyped]
from PIL import Image, UnidentifiedImageError

from novel_platform.application.errors import ApplicationError
from novel_platform.domain.library.models import FileFormat

_CONTAINER_PATH = "META-INF/container.xml"
_MIMETYPE = b"application/epub+zip"
_MAX_CONTAINER_BYTES = 1024 * 1024
_MAX_OPF_BYTES = 5 * 1024 * 1024
_ALLOWED_FONT_OBFUSCATION = {
    "http://www.idpf.org/2008/embedding",
    "http://ns.adobe.com/pdf/enc#RC",
}
_IMAGE_FORMATS = {
    "JPEG": (FileFormat.JPEG, "image/jpeg", ".jpg"),
    "PNG": (FileFormat.PNG, "image/png", ".png"),
    "WEBP": (FileFormat.WEBP, "image/webp", ".webp"),
    "GIF": (FileFormat.GIF, "image/gif", ".gif"),
}


@dataclass(frozen=True, slots=True)
class ParsedCover:
    content: bytes
    thumbnail: bytes
    filename: str
    media_type: str
    file_format: FileFormat


@dataclass(frozen=True, slots=True)
class ParsedEpub:
    metadata: dict[str, object]
    content_item_count: int
    cover: ParsedCover | None
    warnings: list[str] = field(default_factory=list)


def inspect_epub(
    path: Path,
    *,
    max_entry_count: int,
    max_uncompressed_bytes: int,
    max_cover_bytes: int,
    max_cover_pixels: int,
) -> ParsedEpub:
    try:
        archive = zipfile.ZipFile(path)
    except (OSError, zipfile.BadZipFile) as exc:
        raise _error("invalid_epub", "EPUB 不是有效的 ZIP 文件。") from exc

    with archive:
        entries = archive.infolist()
        if len(entries) > max_entry_count:
            raise _error("epub_entry_limit_exceeded", "EPUB 内文件数量超过限制。")
        total_size = 0
        names: set[str] = set()
        for entry in entries:
            _validate_archive_entry(entry)
            if entry.filename in names:
                raise _error("invalid_epub", "EPUB 包含重复的归档条目。")
            total_size += entry.file_size
            if total_size > max_uncompressed_bytes:
                raise _error(
                    "epub_uncompressed_size_exceeded",
                    "EPUB 解压后的总大小超过限制。",
                )
            names.add(entry.filename)

        if not entries or entries[0].filename != "mimetype":
            raise _error("invalid_epub", "EPUB 的第一个归档条目必须是 mimetype。")

        mimetype = _read_entry(archive, "mimetype", max_bytes=256, code="invalid_epub")
        mimetype_info = archive.getinfo("mimetype")
        if mimetype != _MIMETYPE or mimetype_info.compress_type != zipfile.ZIP_STORED:
            raise _error("invalid_epub", "EPUB mimetype 无效。")
        if _CONTAINER_PATH not in names:
            raise _error("invalid_epub", "EPUB 缺少 META-INF/container.xml。")

        _check_drm(archive, names)
        container = _parse_xml(
            _read_entry(
                archive,
                _CONTAINER_PATH,
                max_bytes=_MAX_CONTAINER_BYTES,
                code="invalid_epub",
            ),
            code="invalid_epub",
        )
        rootfile_path = _container_rootfile(container)
        if rootfile_path not in names:
            raise _error("invalid_epub", "EPUB container 指向的 OPF 不存在。")
        opf = _parse_xml(
            _read_entry(archive, rootfile_path, max_bytes=_MAX_OPF_BYTES, code="invalid_epub"),
            code="invalid_epub",
        )
        _validate_opf(opf)
        metadata = _extract_metadata(opf)
        manifest = _extract_manifest(opf, rootfile_path)
        spine_count = _validate_spine(opf, manifest, names)
        metadata["spine_item_count"] = spine_count

        parser_warnings: list[str] = []
        cover: ParsedCover | None = None
        cover_path = _cover_path(opf, manifest)
        _validate_archive_contents(
            archive,
            entries,
            max_uncompressed_bytes=max_uncompressed_bytes,
            tolerated_corrupt_entry=cover_path,
        )
        if cover_path:
            if cover_path not in names:
                parser_warnings.append("EPUB 声明的封面文件不存在，已使用默认封面。")
            else:
                try:
                    cover = _extract_cover(
                        archive,
                        cover_path,
                        max_cover_bytes=max_cover_bytes,
                        max_cover_pixels=max_cover_pixels,
                    )
                except ApplicationError as exc:
                    parser_warnings.append(f"封面无法使用: {exc.message}")

        return ParsedEpub(
            metadata=metadata,
            content_item_count=spine_count,
            cover=cover,
            warnings=parser_warnings,
        )


def _validate_archive_entry(entry: zipfile.ZipInfo) -> None:
    name = entry.filename
    path = PurePosixPath(name)
    mode = entry.external_attr >> 16
    file_type = stat.S_IFMT(mode)
    if (
        not name
        or "\\" in name
        or "\x00" in name
        or path.is_absolute()
        or name.startswith("/")
        or any(part in {"", ".", ".."} for part in path.parts if part != ".")
        or (path.parts and path.parts[0].endswith(":"))
        or stat.S_ISLNK(mode)
        or file_type not in {0, stat.S_IFREG, stat.S_IFDIR}
        or bool(entry.flag_bits & 0x1)
    ):
        code = "epub_drm_unsupported" if entry.flag_bits & 0x1 else "unsafe_archive_path"
        message = "暂不支持加密 EPUB。" if entry.flag_bits & 0x1 else "EPUB 包含不安全的归档路径。"
        raise _error(code, message)


def _validate_archive_contents(
    archive: zipfile.ZipFile,
    entries: list[zipfile.ZipInfo],
    *,
    max_uncompressed_bytes: int,
    tolerated_corrupt_entry: str | None,
) -> None:
    actual_size = 0
    for entry in entries:
        if entry.is_dir():
            continue
        try:
            with archive.open(entry) as source:
                while chunk := source.read(1024 * 1024):
                    actual_size += len(chunk)
                    if actual_size > max_uncompressed_bytes:
                        raise _error(
                            "epub_uncompressed_size_exceeded",
                            "EPUB 实际解压后的总大小超过限制。",
                        )
        except ApplicationError:
            raise
        except (OSError, RuntimeError, EOFError, zipfile.BadZipFile) as exc:
            if entry.filename == tolerated_corrupt_entry:
                continue
            raise _error("invalid_epub", "EPUB 包含损坏的 ZIP 条目。") from exc


def _read_entry(archive: zipfile.ZipFile, name: str, *, max_bytes: int, code: str) -> bytes:
    try:
        info = archive.getinfo(name)
    except KeyError as exc:
        raise _error(code, "EPUB 缺少必需文件。") from exc
    if info.file_size > max_bytes:
        raise _error(code, "EPUB 内部文件超过安全解析限制。")
    try:
        with archive.open(info) as source:
            content = source.read(max_bytes + 1)
    except (OSError, RuntimeError, zipfile.BadZipFile) as exc:
        raise _error(code, "EPUB 内部文件无法读取。") from exc
    if len(content) > max_bytes:
        raise _error(code, "EPUB 内部文件超过安全解析限制。")
    return content


def _parse_xml(content: bytes, *, code: str) -> Element:
    try:
        return cast(Element, fromstring(content))
    except (DefusedXmlException, ParseError, ValueError) as exc:
        raise _error(code, "EPUB XML 无效或包含不安全实体。") from exc


def _container_rootfile(container: Element) -> str:
    if _local_name(container.tag) != "container":
        raise _error("invalid_epub", "EPUB container 根元素无效。")
    for element in container.iter():
        if _local_name(element.tag) == "rootfile":
            if element.attrib.get("media-type") != "application/oebps-package+xml":
                raise _error("invalid_epub", "EPUB container 的 OPF 类型无效。")
            path = element.attrib.get("full-path", "")
            return _safe_internal_path(path)
    raise _error("invalid_epub", "EPUB container 未声明 OPF。")


def _validate_opf(opf: Element) -> None:
    if _local_name(opf.tag) != "package":
        raise _error("invalid_epub", "EPUB OPF 根元素无效。")
    child_names = {_local_name(child.tag) for child in opf}
    if "manifest" not in child_names or "spine" not in child_names:
        raise _error("invalid_epub", "EPUB OPF 缺少 manifest 或 spine。")


def _extract_metadata(opf: Element) -> dict[str, object]:
    values: dict[str, list[str]] = {}
    accepted = {
        "title",
        "creator",
        "language",
        "description",
        "identifier",
        "publisher",
        "date",
        "subject",
    }
    for element in opf.iter():
        name = _local_name(element.tag)
        if name in accepted and element.text:
            value = " ".join(element.text.split())
            if value:
                values.setdefault(name, []).append(value[:5000])

    def first(name: str) -> str | None:
        items = values.get(name, [])
        return items[0] if items else None

    return {
        "title": first("title"),
        "creators": values.get("creator", []),
        "language": first("language"),
        "description": first("description"),
        "identifier": first("identifier"),
        "publisher": first("publisher"),
        "date": first("date"),
        "subjects": values.get("subject", []),
    }


def _extract_manifest(opf: Element, opf_path: str) -> dict[str, dict[str, str]]:
    manifest: dict[str, dict[str, str]] = {}
    seen_item_ids: set[str] = set()
    base = posixpath.dirname(opf_path)
    for element in opf.iter():
        if _local_name(element.tag) != "item":
            continue
        item_id = element.attrib.get("id")
        href = element.attrib.get("href")
        if not item_id or not href:
            continue
        if item_id in seen_item_ids:
            raise _error("invalid_epub", "EPUB manifest 包含重复 ID。")
        seen_item_ids.add(item_id)
        parsed = urlsplit(href)
        if parsed.scheme or parsed.netloc:
            continue
        resolved = _safe_internal_path(posixpath.join(base, unquote(parsed.path)))
        manifest[item_id] = {
            "path": resolved,
            "media_type": element.attrib.get("media-type", ""),
            "properties": element.attrib.get("properties", ""),
        }
    return manifest


def _validate_spine(
    opf: Element,
    manifest: dict[str, dict[str, str]],
    archive_names: set[str],
) -> int:
    spine = next(child for child in opf if _local_name(child.tag) == "spine")
    item_ids = [
        element.attrib.get("idref", "")
        for element in spine
        if _local_name(element.tag) == "itemref"
    ]
    if not item_ids:
        raise _error("invalid_epub", "EPUB spine 不能为空。")
    for item_id in item_ids:
        item = manifest.get(item_id)
        if item is None or item["path"] not in archive_names:
            raise _error("invalid_epub", "EPUB spine 引用了不存在的内容文件。")
    return len(item_ids)


def _cover_path(opf: Element, manifest: dict[str, dict[str, str]]) -> str | None:
    for item in manifest.values():
        if "cover-image" in item["properties"].split():
            return item["path"]
    cover_id: str | None = None
    for element in opf.iter():
        if _local_name(element.tag) == "meta" and element.attrib.get("name", "").lower() == "cover":
            cover_id = element.attrib.get("content")
            break
    if cover_id and cover_id in manifest:
        return manifest[cover_id]["path"]
    return None


def _extract_cover(
    archive: zipfile.ZipFile,
    path: str,
    *,
    max_cover_bytes: int,
    max_cover_pixels: int,
) -> ParsedCover:
    content = _read_entry(
        archive,
        path,
        max_bytes=max_cover_bytes,
        code="invalid_epub",
    )
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(content)) as probe:
                image_format = probe.format
                width, height = probe.size
                if width <= 0 or height <= 0 or width * height > max_cover_pixels:
                    raise _error("invalid_epub", "封面图片尺寸超过限制。")
                probe.verify()
            if not image_format or image_format not in _IMAGE_FORMATS:
                raise _error("invalid_epub", "封面图片格式不受支持。")
            with Image.open(io.BytesIO(content)) as image:
                image.seek(0)
                thumbnail = image.convert("RGB")
                thumbnail.thumbnail((480, 720), Image.Resampling.LANCZOS)
                output = io.BytesIO()
                thumbnail.save(output, format="JPEG", quality=85, optimize=True)
    except ApplicationError:
        raise
    except (
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
        UnidentifiedImageError,
        OSError,
        ValueError,
    ) as exc:
        raise _error("invalid_epub", "封面图片损坏或不受支持。") from exc
    file_format, media_type, suffix = _IMAGE_FORMATS[image_format]
    filename = f"cover{suffix}"
    return ParsedCover(
        content=content,
        thumbnail=output.getvalue(),
        filename=filename,
        media_type=media_type,
        file_format=file_format,
    )


def _check_drm(archive: zipfile.ZipFile, names: set[str]) -> None:
    lowered = {name.lower(): name for name in names}
    if "meta-inf/rights.xml" in lowered:
        raise _error("epub_drm_unsupported", "暂不支持带 DRM 的 EPUB。")
    encryption_name = lowered.get("meta-inf/encryption.xml")
    if not encryption_name:
        return
    encryption = _parse_xml(
        _read_entry(
            archive,
            encryption_name,
            max_bytes=_MAX_CONTAINER_BYTES,
            code="epub_drm_unsupported",
        ),
        code="epub_drm_unsupported",
    )
    algorithms = {
        element.attrib.get("Algorithm", "")
        for element in encryption.iter()
        if _local_name(element.tag) == "EncryptionMethod"
    }
    if not algorithms or any(value not in _ALLOWED_FONT_OBFUSCATION for value in algorithms):
        raise _error("epub_drm_unsupported", "暂不支持带 DRM 的 EPUB。")


def _safe_internal_path(value: str) -> str:
    if not value or "\\" in value or "\x00" in value:
        raise _error("unsafe_archive_path", "EPUB 包含不安全的内部路径。")
    normalized = posixpath.normpath(value)
    path = PurePosixPath(normalized)
    if path.is_absolute() or normalized == ".." or normalized.startswith("../"):
        raise _error("unsafe_archive_path", "EPUB 包含不安全的内部路径。")
    return normalized


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _error(code: str, message: str) -> ApplicationError:
    return ApplicationError(code, message, status_code=422)
