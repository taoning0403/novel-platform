import base64
import io
import zipfile

import pytest

from novel_platform.application.errors import ApplicationError
from novel_platform.application.reader.content import (
    build_epub_publication,
    build_text_publication,
    read_epub_resource,
    read_epub_section,
    read_text_section,
)
from novel_platform.domain.library.models import FileFormat

_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


def reader_epub() -> bytes:
    destination = io.BytesIO()
    container = b"""<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
      <rootfiles><rootfile full-path="OPS/book.opf"/></rootfiles>
    </container>"""
    opf = b"""<package xmlns="http://www.idpf.org/2007/opf" version="3.0">
      <metadata><title>Reader fixture</title></metadata>
      <manifest>
        <item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>
        <item id="c1" href="one.xhtml" media-type="application/xhtml+xml"/>
        <item id="c2" href="two.xhtml" media-type="application/xhtml+xml"/>
        <item id="image" href="image.png" media-type="image/png"/>
      </manifest>
      <spine><itemref idref="c1"/><itemref idref="c2"/></spine>
    </package>"""
    nav = b"""<html xmlns="http://www.w3.org/1999/xhtml"><body><nav>
      <ol><li><a href="one.xhtml">First</a></li>
      <li><a href="two.xhtml">Second</a></li></ol>
    </nav></body></html>"""
    chapter = b"""<html><head><style>body{display:none}</style></head><body>
      <script>alert('unsafe')</script><h1 onclick="steal()">Chapter one</h1>
      <p style="position:fixed">Safe <strong>body</strong>
      <img src="image.png" onerror="steal()" alt="illustration" /></p>
      <iframe src="https://example.test">hidden frame</iframe>
      <img src="https://example.test/tracker.png" /></body></html>"""
    with zipfile.ZipFile(destination, "w") as archive:
        archive.writestr("mimetype", b"application/epub+zip", zipfile.ZIP_STORED)
        archive.writestr("META-INF/container.xml", container)
        archive.writestr("OPS/book.opf", opf)
        archive.writestr("OPS/nav.xhtml", nav)
        archive.writestr("OPS/one.xhtml", chapter)
        archive.writestr("OPS/two.xhtml", b"<html><body><p>Second body</p></body></html>")
        archive.writestr("OPS/image.png", _PNG)
    return destination.getvalue()


def reader_epub_without_toc_with_one_oversized_chapter() -> bytes:
    destination = io.BytesIO()
    container = b"""<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
      <rootfiles><rootfile full-path="OPS/book.opf"/></rootfiles>
    </container>"""
    opf = b"""<package xmlns="http://www.idpf.org/2007/opf" version="3.0">
      <manifest>
        <item id="c1" href="one.xhtml" media-type="application/xhtml+xml"/>
        <item id="c2" href="two.xhtml" media-type="application/xhtml+xml"/>
      </manifest>
      <spine><itemref idref="c1"/><itemref idref="c2"/></spine>
    </package>"""
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("mimetype", b"application/epub+zip", zipfile.ZIP_STORED)
        archive.writestr("META-INF/container.xml", container)
        archive.writestr("OPS/book.opf", opf)
        archive.writestr(
            "OPS/one.xhtml",
            b"<html><body><h1>Fallback chapter</h1><p>Readable body</p></body></html>",
        )
        archive.writestr("OPS/two.xhtml", b"x" * (8 * 1024 * 1024 + 1))
    return destination.getvalue()


def test_epub_reader_uses_spine_toc_and_sanitizes_active_content() -> None:
    content = reader_epub()
    publication = build_epub_publication(io.BytesIO(content), file_revision=3)

    assert publication.file_format is FileFormat.EPUB
    assert publication.file_revision == 3
    assert [section.title for section in publication.sections] == ["First", "Second"]
    assert [item.title for item in publication.toc] == ["First", "Second"]

    section = read_epub_section(io.BytesIO(content), publication, publication.sections[0].id)
    assert "Safe <strong>body</strong>" in section.html
    assert "data-reader-block" in section.html
    assert "data-reader-resource" in section.html
    for forbidden in ("script", "onclick", "onerror", "style=", "iframe", "https://"):
        assert forbidden not in section.html
    assert len(section.resource_ids) == 1

    image = read_epub_resource(
        io.BytesIO(content),
        publication,
        section.resource_ids[0],
        max_bytes=1024,
        max_pixels=100,
    )
    assert image.content == _PNG
    assert image.media_type == "image/png"


def test_epub_reader_rejects_unknown_sections_and_resources() -> None:
    content = reader_epub()
    publication = build_epub_publication(io.BytesIO(content), file_revision=1)
    with pytest.raises(ApplicationError) as section:
        read_epub_section(io.BytesIO(content), publication, "s-missing")
    assert section.value.code == "reader_section_not_found"
    with pytest.raises(ApplicationError) as resource:
        read_epub_resource(
            io.BytesIO(content),
            publication,
            "r-missing",
            max_bytes=1024,
            max_pixels=100,
        )
    assert resource.value.code == "reader_resource_not_found"


def test_epub_without_toc_uses_spine_navigation_and_isolates_a_broken_chapter() -> None:
    content = reader_epub_without_toc_with_one_oversized_chapter()
    publication = build_epub_publication(io.BytesIO(content), file_revision=1)

    assert [item.title for item in publication.toc] == ["Fallback chapter", "第 2 节"]
    readable = read_epub_section(io.BytesIO(content), publication, publication.sections[0].id)
    assert "Readable body" in readable.html
    with pytest.raises(ApplicationError) as unavailable:
        read_epub_section(io.BytesIO(content), publication, publication.sections[1].id)
    assert unavailable.value.code == "reader_section_unavailable"


def test_txt_reader_builds_bounded_stable_navigation_and_preserves_paragraphs() -> None:
    content = (
        "第一章\n第一段。\n\n第二段。\n" + ("长文本。" * 25_000) + "\n第二章\n结尾。\n"
    ).encode()
    publication = build_text_publication(io.BytesIO(content), file_revision=2)
    rebuilt = build_text_publication(io.BytesIO(content), file_revision=2)

    assert publication.file_format is FileFormat.TXT
    assert publication.file_revision == 2
    assert len(publication.sections) >= 2
    assert publication.sections[0].title == "第一章"
    assert len({section.id for section in publication.sections}) == len(publication.sections)
    assert [section.id for section in publication.sections] == [
        section.id for section in rebuilt.sections
    ]
    largest_section = max(
        (section.end or 0) - (section.start or 0) for section in publication.sections
    )
    assert largest_section < 140_000

    first = read_text_section(io.BytesIO(content), publication, publication.sections[0].id)
    restored = read_text_section(io.BytesIO(content), rebuilt, rebuilt.sections[0].id)
    assert "第一段。" in first.html
    assert "<p data-reader-block=" in first.html
    assert first.html == restored.html
    assert "\n\n" not in first.html
