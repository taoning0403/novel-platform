import hashlib
import html
import io
import posixpath
import re
import stat
import warnings
import zipfile
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import PurePosixPath
from typing import BinaryIO, cast
from urllib.parse import unquote, urlsplit
from xml.etree.ElementTree import Element, ParseError

from charset_normalizer import from_bytes
from defusedxml.common import DefusedXmlException  # type: ignore[import-untyped]
from defusedxml.ElementTree import fromstring  # type: ignore[import-untyped]
from PIL import Image, UnidentifiedImageError

from novel_platform.application.errors import ApplicationError
from novel_platform.domain.library.models import FileFormat

_CONTAINER_PATH = "META-INF/container.xml"
_MIMETYPE = b"application/epub+zip"
_MAX_CONTAINER_BYTES = 1024 * 1024
_MAX_OPF_BYTES = 5 * 1024 * 1024
_MAX_NAV_BYTES = 3 * 1024 * 1024
_MAX_SECTION_BYTES = 8 * 1024 * 1024
_TXT_SECTION_TARGET_BYTES = 64 * 1024
_SUPPORTED_IMAGE_MEDIA = {
    "image/jpeg": "JPEG",
    "image/png": "PNG",
    "image/gif": "GIF",
    "image/webp": "WEBP",
}
_CHAPTER_PATTERN = re.compile(
    r"^\s*(?:第[0-9\uff10-\uff19一二三四五六七八九十百千万零\u3007两]+[章节回卷]|chapter\s+\d+)\b",
    re.IGNORECASE,
)
_SAFE_TAGS = {
    "a",
    "abbr",
    "b",
    "blockquote",
    "br",
    "cite",
    "code",
    "dd",
    "del",
    "div",
    "dl",
    "dt",
    "em",
    "figcaption",
    "figure",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "hr",
    "i",
    "img",
    "li",
    "ol",
    "p",
    "pre",
    "q",
    "s",
    "small",
    "span",
    "strong",
    "sub",
    "sup",
    "table",
    "tbody",
    "td",
    "tfoot",
    "th",
    "thead",
    "tr",
    "u",
    "ul",
}
_VOID_TAGS = {"br", "hr", "img"}
_BLOCK_TAGS = {
    "blockquote",
    "dd",
    "div",
    "dt",
    "figcaption",
    "figure",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "li",
    "p",
    "pre",
    "table",
    "tr",
}
_DROP_WITH_CONTENT = {
    "audio",
    "button",
    "canvas",
    "embed",
    "form",
    "iframe",
    "input",
    "link",
    "math",
    "meta",
    "noscript",
    "object",
    "script",
    "select",
    "style",
    "textarea",
    "video",
}


@dataclass(frozen=True, slots=True)
class ReaderSection:
    id: str
    index: int
    title: str
    path: str | None = None
    start: int | None = None
    end: int | None = None


@dataclass(frozen=True, slots=True)
class ReaderTocItem:
    title: str
    section_id: str


@dataclass(frozen=True, slots=True)
class ReaderResource:
    id: str
    path: str
    media_type: str


@dataclass(frozen=True, slots=True)
class ReaderPublication:
    file_format: FileFormat
    file_revision: int
    sections: tuple[ReaderSection, ...]
    toc: tuple[ReaderTocItem, ...]
    resources: tuple[ReaderResource, ...] = ()


@dataclass(frozen=True, slots=True)
class ReaderSectionContent:
    section: ReaderSection
    html: str
    resource_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ReaderResourceContent:
    content: bytes
    media_type: str


@dataclass(frozen=True, slots=True)
class _ManifestItem:
    path: str
    media_type: str
    properties: frozenset[str]


def build_epub_publication(source: BinaryIO, *, file_revision: int) -> ReaderPublication:
    try:
        archive = zipfile.ZipFile(source)
    except (OSError, zipfile.BadZipFile) as exc:
        raise _reader_error("reader_epub_invalid", "EPUB 文件损坏，无法打开阅读。") from exc
    with archive:
        names = _validated_archive_names(archive)
        opf_path, opf = _epub_opf(archive, names)
        manifest = _manifest(opf, opf_path)
        spine_ids = _spine_ids(opf)
        section_items: list[_ManifestItem] = []
        for item_id in spine_ids:
            item = manifest.get(item_id)
            if item is None or item.path not in names:
                raise _reader_error(
                    "reader_epub_invalid",
                    "EPUB 阅读顺序引用了缺失的正文。",
                )
            section_items.append(item)

        path_to_section: dict[str, ReaderSection] = {}
        sections: list[ReaderSection] = []
        for index, item in enumerate(section_items):
            section = ReaderSection(
                id=_opaque_id("s", item.path),
                index=index,
                title=f"第 {index + 1} 节",
                path=item.path,
            )
            sections.append(section)
            path_to_section[item.path] = section

        toc_pairs = _extract_toc(archive, manifest, path_to_section)
        labels = {section_id: title for title, section_id in toc_pairs}
        titled_sections: list[ReaderSection] = []
        for section in sections:
            title = labels.get(section.id)
            if not title and section.path:
                title = _document_title(archive, section.path)
            titled_sections.append(
                ReaderSection(
                    id=section.id,
                    index=section.index,
                    title=title or section.title,
                    path=section.path,
                )
            )
        if not toc_pairs:
            toc_pairs = [(section.title, section.id) for section in titled_sections]

        resources = tuple(
            ReaderResource(
                id=_opaque_id("r", item.path),
                path=item.path,
                media_type=item.media_type,
            )
            for item in manifest.values()
            if item.path in names and item.media_type in _SUPPORTED_IMAGE_MEDIA
        )
        return ReaderPublication(
            file_format=FileFormat.EPUB,
            file_revision=file_revision,
            sections=tuple(titled_sections),
            toc=tuple(
                ReaderTocItem(title=title, section_id=section_id) for title, section_id in toc_pairs
            ),
            resources=resources,
        )


def read_epub_section(
    source: BinaryIO,
    publication: ReaderPublication,
    section_id: str,
) -> ReaderSectionContent:
    section = next((item for item in publication.sections if item.id == section_id), None)
    if section is None or section.path is None:
        raise _reader_error("reader_section_not_found", "阅读章节不存在。", status_code=404)
    try:
        archive = zipfile.ZipFile(source)
    except (OSError, zipfile.BadZipFile) as exc:
        raise _reader_error("reader_epub_invalid", "EPUB 文件损坏，无法打开阅读。") from exc
    with archive:
        content = _read_entry(
            archive,
            section.path,
            max_bytes=_MAX_SECTION_BYTES,
            code="reader_section_unavailable",
            message="此章节损坏或过大，暂时无法显示。",
        )
    resource_map = {item.path: item.id for item in publication.resources}
    sanitizer = _EpubSanitizer(
        section.path,
        resource_map,
        requires_body=b"<body" in content.lower(),
    )
    try:
        sanitizer.feed(_decode_markup(content))
        sanitizer.close()
    except (ValueError, UnicodeError) as exc:
        raise _reader_error(
            "reader_section_unavailable",
            "此章节编码无效，暂时无法显示。",
        ) from exc
    rendered = sanitizer.rendered.strip()
    if not rendered or not sanitizer.has_readable_content:
        raise _reader_error("reader_section_empty", "此章节没有可显示的正文。")
    return ReaderSectionContent(
        section=section,
        html=rendered,
        resource_ids=tuple(sorted(sanitizer.resource_ids)),
    )


def read_epub_resource(
    source: BinaryIO,
    publication: ReaderPublication,
    resource_id: str,
    *,
    max_bytes: int,
    max_pixels: int,
) -> ReaderResourceContent:
    resource = next((item for item in publication.resources if item.id == resource_id), None)
    if resource is None:
        raise _reader_error("reader_resource_not_found", "书内资源不存在。", status_code=404)
    try:
        archive = zipfile.ZipFile(source)
    except (OSError, zipfile.BadZipFile) as exc:
        raise _reader_error("reader_epub_invalid", "EPUB 文件损坏，无法打开阅读。") from exc
    with archive:
        content = _read_entry(
            archive,
            resource.path,
            max_bytes=max_bytes,
            code="reader_resource_unavailable",
            message="书内图片损坏或超过安全限制。",
        )
    expected_format = _SUPPORTED_IMAGE_MEDIA[resource.media_type]
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(content)) as image:
                if image.format != expected_format:
                    raise ValueError("image format mismatch")
                width, height = image.size
                if width <= 0 or height <= 0 or width * height > max_pixels:
                    raise ValueError("image dimensions exceed limit")
                image.verify()
    except (
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
        UnidentifiedImageError,
        OSError,
        ValueError,
    ) as exc:
        raise _reader_error(
            "reader_resource_unavailable",
            "书内图片损坏或超过安全限制。",
        ) from exc
    return ReaderResourceContent(content=content, media_type=resource.media_type)


def build_text_publication(source: BinaryIO, *, file_revision: int) -> ReaderPublication:
    sections: list[ReaderSection] = []
    section_start = 0
    section_title: str | None = None
    while True:
        line_start = source.tell()
        line = source.readline(_TXT_SECTION_TARGET_BYTES + 1)
        if not line:
            break
        line = _align_utf8_chunk(source, line)
        line_end = source.tell()
        is_heading = _text_heading(line)
        if line_start > section_start and (
            is_heading or line_start - section_start >= _TXT_SECTION_TARGET_BYTES
        ):
            sections.append(
                _text_section(
                    len(sections),
                    section_start,
                    line_start,
                    section_title,
                )
            )
            section_start = line_start
            section_title = None
        if section_title is None and is_heading:
            section_title = _line_title(line)
        if line_end - line_start > _TXT_SECTION_TARGET_BYTES and line_start == section_start:
            sections.append(_text_section(len(sections), section_start, line_end, section_title))
            section_start = line_end
            section_title = None
    end = source.tell()
    if end > section_start:
        sections.append(_text_section(len(sections), section_start, end, section_title))
    if not sections:
        raise _reader_error("reader_text_empty", "TXT 没有可显示的正文。")
    return ReaderPublication(
        file_format=FileFormat.TXT,
        file_revision=file_revision,
        sections=tuple(sections),
        toc=tuple(ReaderTocItem(section.title, section.id) for section in sections),
    )


def read_text_section(
    source: BinaryIO,
    publication: ReaderPublication,
    section_id: str,
) -> ReaderSectionContent:
    section = next((item for item in publication.sections if item.id == section_id), None)
    if section is None or section.start is None or section.end is None:
        raise _reader_error("reader_section_not_found", "阅读片段不存在。", status_code=404)
    source.seek(section.start)
    content = source.read(section.end - section.start)
    try:
        decoded = content.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise _reader_error(
            "reader_section_unavailable",
            "规范化 TXT 内容损坏，无法显示此片段。",
        ) from exc
    normalized = decoded.replace("\r\n", "\n").replace("\r", "\n")
    paragraphs = [part for part in re.split(r"\n[\t ]*\n+", normalized) if part.strip()]
    rendered: list[str] = []
    for index, paragraph in enumerate(paragraphs):
        safe = html.escape(paragraph.strip()).replace("\n", "<br />")
        rendered.append(f'<p data-reader-block="b{index + 1:05d}">{safe}</p>')
    if not rendered:
        raise _reader_error("reader_section_empty", "此片段没有可显示的正文。")
    return ReaderSectionContent(section=section, html="".join(rendered), resource_ids=())


def _validated_archive_names(archive: zipfile.ZipFile) -> set[str]:
    entries = archive.infolist()
    if not entries or entries[0].filename != "mimetype":
        raise _reader_error("reader_epub_invalid", "EPUB 缺少有效的 mimetype。")
    if len(entries) > 10_000:
        raise _reader_error("reader_epub_invalid", "EPUB 内文件数量超过安全限制。")
    names: set[str] = set()
    for entry in entries:
        name = entry.filename
        path = PurePosixPath(name)
        mode = entry.external_attr >> 16
        file_type = stat.S_IFMT(mode)
        if (
            not name
            or name in names
            or "\\" in name
            or "\x00" in name
            or path.is_absolute()
            or any(part in {"", ".."} for part in path.parts)
            or stat.S_ISLNK(mode)
            or file_type not in {0, stat.S_IFREG, stat.S_IFDIR}
            or bool(entry.flag_bits & 0x1)
        ):
            raise _reader_error("reader_epub_invalid", "EPUB 包含不安全的内部文件。")
        names.add(name)
    if _CONTAINER_PATH not in names:
        raise _reader_error("reader_epub_invalid", "EPUB 缺少 container.xml。")
    mimetype = _read_entry(
        archive,
        "mimetype",
        max_bytes=256,
        code="reader_epub_invalid",
        message="EPUB mimetype 无效。",
    )
    if mimetype != _MIMETYPE:
        raise _reader_error("reader_epub_invalid", "EPUB mimetype 无效。")
    return names


def _epub_opf(archive: zipfile.ZipFile, names: set[str]) -> tuple[str, Element]:
    container = _parse_xml(
        _read_entry(
            archive,
            _CONTAINER_PATH,
            max_bytes=_MAX_CONTAINER_BYTES,
            code="reader_epub_invalid",
            message="EPUB container 无效。",
        )
    )
    opf_path: str | None = None
    for element in container.iter():
        if _local_name(element.tag) == "rootfile":
            opf_path = _safe_path(element.attrib.get("full-path", ""))
            break
    if opf_path is None or opf_path not in names:
        raise _reader_error("reader_epub_invalid", "EPUB 指向的 OPF 不存在。")
    opf = _parse_xml(
        _read_entry(
            archive,
            opf_path,
            max_bytes=_MAX_OPF_BYTES,
            code="reader_epub_invalid",
            message="EPUB OPF 无效。",
        )
    )
    return opf_path, opf


def _manifest(opf: Element, opf_path: str) -> dict[str, _ManifestItem]:
    base = posixpath.dirname(opf_path)
    result: dict[str, _ManifestItem] = {}
    for element in opf.iter():
        if _local_name(element.tag) != "item":
            continue
        item_id = element.attrib.get("id")
        href = element.attrib.get("href")
        if not item_id or not href or item_id in result:
            continue
        parsed = urlsplit(href)
        if parsed.scheme or parsed.netloc:
            continue
        path = _safe_path(posixpath.join(base, unquote(parsed.path)))
        result[item_id] = _ManifestItem(
            path=path,
            media_type=element.attrib.get("media-type", "").lower(),
            properties=frozenset(element.attrib.get("properties", "").split()),
        )
    return result


def _spine_ids(opf: Element) -> list[str]:
    spine = next((child for child in opf if _local_name(child.tag) == "spine"), None)
    if spine is None:
        raise _reader_error("reader_epub_invalid", "EPUB 缺少阅读顺序。")
    result = [
        element.attrib.get("idref", "")
        for element in spine
        if _local_name(element.tag) == "itemref" and element.attrib.get("idref")
    ]
    if not result:
        raise _reader_error("reader_epub_invalid", "EPUB 阅读顺序为空。")
    return result


def _extract_toc(
    archive: zipfile.ZipFile,
    manifest: dict[str, _ManifestItem],
    path_to_section: dict[str, ReaderSection],
) -> list[tuple[str, str]]:
    nav_item = next((item for item in manifest.values() if "nav" in item.properties), None)
    if nav_item is not None:
        pairs = _toc_from_nav(archive, nav_item.path, path_to_section)
        if pairs:
            return pairs
    ncx_item = next(
        (item for item in manifest.values() if item.media_type == "application/x-dtbncx+xml"),
        None,
    )
    if ncx_item is not None:
        return _toc_from_ncx(archive, ncx_item.path, path_to_section)
    return []


def _toc_from_nav(
    archive: zipfile.ZipFile,
    nav_path: str,
    path_to_section: dict[str, ReaderSection],
) -> list[tuple[str, str]]:
    try:
        root = _parse_xml(
            _read_entry(
                archive,
                nav_path,
                max_bytes=_MAX_NAV_BYTES,
                code="reader_toc_invalid",
                message="EPUB 目录损坏，已使用正文顺序导航。",
            )
        )
    except ApplicationError:
        return []
    base = posixpath.dirname(nav_path)
    result: list[tuple[str, str]] = []
    for element in root.iter():
        if _local_name(element.tag) != "a":
            continue
        href = element.attrib.get("href", "")
        parsed = urlsplit(href)
        if parsed.scheme or parsed.netloc or not parsed.path:
            continue
        try:
            target = _safe_path(posixpath.join(base, unquote(parsed.path)))
        except ApplicationError:
            continue
        section = path_to_section.get(target)
        title = " ".join("".join(element.itertext()).split())[:300]
        if section and title and (title, section.id) not in result:
            result.append((title, section.id))
    return result


def _toc_from_ncx(
    archive: zipfile.ZipFile,
    ncx_path: str,
    path_to_section: dict[str, ReaderSection],
) -> list[tuple[str, str]]:
    try:
        root = _parse_xml(
            _read_entry(
                archive,
                ncx_path,
                max_bytes=_MAX_NAV_BYTES,
                code="reader_toc_invalid",
                message="EPUB 目录损坏，已使用正文顺序导航。",
            )
        )
    except ApplicationError:
        return []
    base = posixpath.dirname(ncx_path)
    result: list[tuple[str, str]] = []
    for point in root.iter():
        if _local_name(point.tag) != "navPoint":
            continue
        label = next((item for item in point.iter() if _local_name(item.tag) == "text"), None)
        content = next((item for item in point.iter() if _local_name(item.tag) == "content"), None)
        if label is None or content is None or not label.text:
            continue
        parsed = urlsplit(content.attrib.get("src", ""))
        if parsed.scheme or parsed.netloc or not parsed.path:
            continue
        try:
            target = _safe_path(posixpath.join(base, unquote(parsed.path)))
        except ApplicationError:
            continue
        section = path_to_section.get(target)
        title = " ".join(label.text.split())[:300]
        if section and title and (title, section.id) not in result:
            result.append((title, section.id))
    return result


def _document_title(archive: zipfile.ZipFile, path: str) -> str | None:
    try:
        content = _read_entry(
            archive,
            path,
            max_bytes=min(_MAX_SECTION_BYTES, 1024 * 1024),
            code="reader_section_unavailable",
            message="章节无法读取。",
        )
        root = _parse_xml(content)
    except ApplicationError:
        return None
    for accepted in ("h1", "h2", "title"):
        for element in root.iter():
            if _local_name(element.tag).lower() == accepted:
                title = " ".join("".join(element.itertext()).split())[:300]
                if title:
                    return title
    return None


class _EpubSanitizer(HTMLParser):
    def __init__(
        self,
        section_path: str,
        resource_map: dict[str, str],
        *,
        requires_body: bool,
    ) -> None:
        super().__init__(convert_charrefs=True)
        self.section_path = section_path
        self.resource_map = resource_map
        self.requires_body = requires_body
        self.in_body = not requires_body
        self.skip_depth = 0
        self.svg_depth = 0
        self.parts: list[str] = []
        self.block_count = 0
        self.resource_ids: set[str] = set()
        self.has_readable_content = False

    @property
    def rendered(self) -> str:
        return "".join(self.parts)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        lowered = tag.lower()
        if lowered == "body":
            self.in_body = True
            return
        if not self.in_body:
            return
        if self.skip_depth:
            if lowered in _DROP_WITH_CONTENT:
                self.skip_depth += 1
            return
        if lowered in _DROP_WITH_CONTENT:
            self.skip_depth = 1
            return
        if lowered == "svg":
            self.svg_depth += 1
            return
        if self.svg_depth:
            if lowered == "image":
                attribute_map = {name.lower(): value for name, value in attrs if value is not None}
                self._append_svg_image(attribute_map)
            return
        if lowered not in _SAFE_TAGS:
            return
        attribute_map = {name.lower(): value for name, value in attrs if value is not None}
        safe_attrs: list[tuple[str, str]] = []
        for name in ("colspan", "rowspan", "lang", "dir", "title"):
            value = attribute_map.get(name)
            if value and len(value) <= 300:
                safe_attrs.append((name, value))
        if lowered in _BLOCK_TAGS:
            self.block_count += 1
            safe_attrs.append(("data-reader-block", f"b{self.block_count:05d}"))
        if lowered == "img":
            resource_id = self._resource_id(attribute_map.get("src", ""))
            if resource_id is None:
                return
            safe_attrs.append(("data-reader-resource", resource_id))
            safe_attrs.append(("alt", attribute_map.get("alt", "")[:500]))
            self.resource_ids.add(resource_id)
            self.has_readable_content = True
        elif lowered == "a":
            safe_attrs.append(("role", "link"))
        rendered_attrs = "".join(
            f' {name}="{html.escape(value, quote=True)}"' for name, value in safe_attrs
        )
        self.parts.append(f"<{lowered}{rendered_attrs}>")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        lowered = tag.lower()
        if lowered == "body":
            self.in_body = False
            return
        if not self.in_body:
            return
        if self.skip_depth:
            if lowered in _DROP_WITH_CONTENT:
                self.skip_depth -= 1
            return
        if lowered == "svg":
            if self.svg_depth:
                self.svg_depth -= 1
            return
        if self.svg_depth:
            return
        if lowered in _SAFE_TAGS and lowered not in _VOID_TAGS:
            self.parts.append(f"</{lowered}>")

    def handle_data(self, data: str) -> None:
        if not self.in_body or self.skip_depth or self.svg_depth:
            return
        if data.strip():
            self.has_readable_content = True
        self.parts.append(html.escape(data))

    def _resource_id(self, value: str) -> str | None:
        parsed = urlsplit(value)
        if parsed.scheme or parsed.netloc or not parsed.path:
            return None
        try:
            path = _safe_path(
                posixpath.join(posixpath.dirname(self.section_path), unquote(parsed.path))
            )
        except ApplicationError:
            return None
        return self.resource_map.get(path)

    def _append_svg_image(self, attribute_map: dict[str, str]) -> None:
        source = attribute_map.get("href") or attribute_map.get("xlink:href") or ""
        resource_id = self._resource_id(source)
        if resource_id is None:
            return
        alt = attribute_map.get("aria-label") or attribute_map.get("title") or ""
        safe_attrs = [
            ("data-reader-resource", resource_id),
            ("alt", alt[:500]),
        ]
        title = attribute_map.get("title")
        if title and len(title) <= 300:
            safe_attrs.append(("title", title))
        rendered_attrs = "".join(
            f' {name}="{html.escape(value, quote=True)}"' for name, value in safe_attrs
        )
        self.parts.append(f"<img{rendered_attrs}>")
        self.resource_ids.add(resource_id)
        self.has_readable_content = True


def _read_entry(
    archive: zipfile.ZipFile,
    name: str,
    *,
    max_bytes: int,
    code: str,
    message: str,
) -> bytes:
    try:
        info = archive.getinfo(name)
        if info.file_size > max_bytes:
            raise _reader_error(code, message)
        with archive.open(info) as stream:
            content = stream.read(max_bytes + 1)
    except ApplicationError:
        raise
    except (KeyError, OSError, RuntimeError, EOFError, zipfile.BadZipFile) as exc:
        raise _reader_error(code, message) from exc
    if len(content) > max_bytes:
        raise _reader_error(code, message)
    return content


def _parse_xml(content: bytes) -> Element:
    try:
        return cast(Element, fromstring(content))
    except (DefusedXmlException, ParseError, ValueError) as exc:
        raise _reader_error("reader_epub_invalid", "EPUB XML 无效或不安全。") from exc


def _decode_markup(content: bytes) -> str:
    try:
        return content.decode("utf-8-sig", errors="strict")
    except UnicodeDecodeError:
        match = from_bytes(content).best()
        if match is None or not match.encoding or match.percent_chaos > 20:
            raise
        return str(match)


def _safe_path(value: str) -> str:
    if not value or "\\" in value or "\x00" in value:
        raise _reader_error("reader_epub_invalid", "EPUB 包含不安全的内部路径。")
    normalized = posixpath.normpath(value)
    path = PurePosixPath(normalized)
    if path.is_absolute() or normalized == ".." or normalized.startswith("../"):
        raise _reader_error("reader_epub_invalid", "EPUB 包含不安全的内部路径。")
    return normalized


def _text_heading(line: bytes) -> bool:
    if len(line) > 1000:
        return False
    try:
        return bool(_CHAPTER_PATTERN.match(line.decode("utf-8", errors="strict")))
    except UnicodeDecodeError:
        raise _reader_error("reader_text_invalid", "规范化 TXT 内容损坏。") from None


def _align_utf8_chunk(source: BinaryIO, line: bytes) -> bytes:
    if line.endswith(b"\n"):
        return line
    for trim in range(4):
        candidate = line if trim == 0 else line[:-trim]
        try:
            candidate.decode("utf-8", errors="strict")
        except UnicodeDecodeError:
            continue
        if trim:
            source.seek(-trim, io.SEEK_CUR)
        return candidate
    raise _reader_error("reader_text_invalid", "规范化 TXT 内容损坏。")


def _line_title(line: bytes) -> str | None:
    try:
        title = " ".join(line.decode("utf-8", errors="strict").split())[:300]
    except UnicodeDecodeError:
        return None
    return title or None


def _text_section(index: int, start: int, end: int, title: str | None) -> ReaderSection:
    return ReaderSection(
        id=_opaque_id("t", f"{start}:{end}"),
        index=index,
        title=title or f"第 {index + 1} 段",
        start=start,
        end=end,
    )


def _opaque_id(prefix: str, value: str) -> str:
    return f"{prefix}-{hashlib.sha256(value.encode()).hexdigest()[:24]}"


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _reader_error(code: str, message: str, *, status_code: int = 422) -> ApplicationError:
    return ApplicationError(code, message, status_code=status_code)
