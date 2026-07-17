import base64
import io
import stat
import zipfile
from pathlib import Path

import pytest
from PIL import Image

from novel_platform.application.errors import ApplicationError
from novel_platform.application.library.epub import inspect_epub
from novel_platform.domain.library.models import FileFormat

_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)
_CONTAINER = b"""<?xml version="1.0"?>
<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container" version="1.0">
  <rootfiles><rootfile full-path="OEBPS/content.opf"
    media-type="application/oebps-package+xml"/></rootfiles>
</container>
"""
_OPF = b"""<?xml version="1.0"?>
<package xmlns="http://www.idpf.org/2007/opf"
  xmlns:dc="http://purl.org/dc/elements/1.1/" version="3.0">
  <metadata>
    <dc:title>Test Novel</dc:title><dc:creator>Test Author</dc:creator>
    <dc:language>en</dc:language><dc:description>Safe fixture</dc:description>
    <dc:identifier>fixture-1</dc:identifier><dc:subject>test</dc:subject>
  </metadata>
  <manifest>
    <item id="cover" href="cover.png" media-type="image/png" properties="cover-image"/>
    <item id="chapter" href="chapter.xhtml" media-type="application/xhtml+xml"/>
  </manifest>
  <spine><itemref idref="chapter"/></spine>
</package>
"""


def make_epub(
    path: Path,
    *,
    opf: bytes = _OPF,
    cover: bytes = _PNG,
    extra: dict[str, bytes] | None = None,
    symlink_name: str | None = None,
) -> Path:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("mimetype", b"application/epub+zip", compress_type=zipfile.ZIP_STORED)
        archive.writestr("META-INF/container.xml", _CONTAINER)
        archive.writestr("OEBPS/content.opf", opf)
        archive.writestr("OEBPS/cover.png", cover)
        archive.writestr("OEBPS/chapter.xhtml", b"<html><body>fixture</body></html>")
        for name, content in (extra or {}).items():
            archive.writestr(name, content)
        if symlink_name:
            info = zipfile.ZipInfo(symlink_name)
            info.create_system = 3
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            archive.writestr(info, b"../../outside")
    return path


def parse(path: Path, **overrides: int):  # type: ignore[no-untyped-def]
    limits = {
        "max_entry_count": 100,
        "max_uncompressed_bytes": 1024 * 1024,
        "max_cover_bytes": 1024 * 1024,
        "max_cover_pixels": 100_000,
        **overrides,
    }
    return inspect_epub(path, **limits)


def test_epub_metadata_spine_and_cover_are_extracted(tmp_path: Path) -> None:
    parsed = parse(make_epub(tmp_path / "fixture.epub"))
    assert parsed.metadata["title"] == "Test Novel"
    assert parsed.metadata["creators"] == ["Test Author"]
    assert parsed.metadata["language"] == "en"
    assert parsed.content_item_count == 1
    assert parsed.cover is not None
    assert parsed.cover.file_format is FileFormat.PNG
    assert parsed.cover.thumbnail.startswith(b"\xff\xd8")


@pytest.mark.parametrize(
    ("extra", "symlink", "expected_code"),
    [
        ({"../outside.txt": b"bad"}, None, "unsafe_archive_path"),
        ({"/absolute.txt": b"bad"}, None, "unsafe_archive_path"),
        ({}, "OEBPS/link", "unsafe_archive_path"),
    ],
)
def test_epub_rejects_unsafe_archive_entries(
    tmp_path: Path,
    extra: dict[str, bytes],
    symlink: str | None,
    expected_code: str,
) -> None:
    with pytest.raises(ApplicationError) as caught:
        parse(make_epub(tmp_path / "unsafe.epub", extra=extra, symlink_name=symlink))
    assert caught.value.code == expected_code


def test_epub_rejects_non_regular_archive_entries(tmp_path: Path) -> None:
    path = make_epub(tmp_path / "special.epub")
    with zipfile.ZipFile(path, "a") as archive:
        info = zipfile.ZipInfo("OEBPS/pipe")
        info.create_system = 3
        info.external_attr = (stat.S_IFIFO | 0o600) << 16
        archive.writestr(info, b"")
    with pytest.raises(ApplicationError) as caught:
        parse(path)
    assert caught.value.code == "unsafe_archive_path"


def test_epub_rejects_entry_and_uncompressed_size_limits(tmp_path: Path) -> None:
    path = make_epub(tmp_path / "large.epub", extra={"OEBPS/large.bin": b"x" * 1000})
    with pytest.raises(ApplicationError) as entries:
        parse(path, max_entry_count=2)
    assert entries.value.code == "epub_entry_limit_exceeded"
    with pytest.raises(ApplicationError) as size:
        parse(path, max_uncompressed_bytes=200)
    assert size.value.code == "epub_uncompressed_size_exceeded"


def test_epub_rejects_external_entities_and_drm(tmp_path: Path) -> None:
    unsafe_opf = b"""<!DOCTYPE package [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>
    <package xmlns="http://www.idpf.org/2007/opf"><metadata><title>&xxe;</title></metadata></package>"""
    with pytest.raises(ApplicationError) as xml_error:
        parse(make_epub(tmp_path / "xxe.epub", opf=unsafe_opf))
    assert xml_error.value.code == "invalid_epub"

    encryption = b"""<encryption xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
      <EncryptedData><EncryptionMethod Algorithm="urn:example:drm"/></EncryptedData>
    </encryption>"""
    with pytest.raises(ApplicationError) as drm_error:
        parse(
            make_epub(
                tmp_path / "drm.epub",
                extra={"META-INF/encryption.xml": encryption},
            )
        )
    assert drm_error.value.code == "epub_drm_unsupported"


def test_broken_or_oversized_cover_is_warning_not_import_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    broken = parse(make_epub(tmp_path / "broken-cover.epub", cover=b"not an image"))
    assert broken.cover is None
    assert broken.warnings

    oversized = parse(make_epub(tmp_path / "large-cover.epub"), max_cover_bytes=8)
    assert oversized.cover is None
    assert oversized.warnings

    image_bytes = io.BytesIO()
    Image.new("RGB", (2, 2), "white").save(image_bytes, format="PNG")
    oversized_dimensions = parse(
        make_epub(tmp_path / "large-dimensions.epub", cover=image_bytes.getvalue()),
        max_cover_pixels=1,
    )
    assert oversized_dimensions.cover is None
    assert oversized_dimensions.warnings

    warning_image = io.BytesIO()
    Image.new("RGB", (2, 1), "white").save(warning_image, format="PNG")
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 1)
    decompression_warning = parse(
        make_epub(tmp_path / "decompression-warning.epub", cover=warning_image.getvalue()),
    )
    assert decompression_warning.cover is None
    assert decompression_warning.warnings


def test_fake_epub_is_rejected(tmp_path: Path) -> None:
    fake = tmp_path / "fake.epub"
    fake.write_text("not a zip", encoding="utf-8")
    with pytest.raises(ApplicationError) as caught:
        parse(fake)
    assert caught.value.code == "invalid_epub"


def test_epub_with_corrupt_entry_crc_is_rejected(tmp_path: Path) -> None:
    path = make_epub(tmp_path / "corrupt.epub")
    content = path.read_bytes()
    assert b"fixture" in content
    path.write_bytes(content.replace(b"fixture", b"corrupt", 1))
    with pytest.raises(ApplicationError) as caught:
        parse(path)
    assert caught.value.code == "invalid_epub"


def test_epub_with_corrupt_cover_crc_uses_a_warning(tmp_path: Path) -> None:
    path = make_epub(tmp_path / "corrupt-cover.epub")
    content = bytearray(path.read_bytes())
    cover_offset = content.find(_PNG)
    assert cover_offset >= 0
    content[cover_offset + len(_PNG) // 2] ^= 0x01
    path.write_bytes(content)

    parsed = parse(path)

    assert parsed.cover is None
    assert parsed.warnings


def test_epub_rejects_duplicate_entries(tmp_path: Path) -> None:
    path = make_epub(tmp_path / "duplicate.epub", extra={"OEBPS/content.opf": _OPF})
    with pytest.raises(ApplicationError) as caught:
        parse(path)
    assert caught.value.code == "invalid_epub"


def test_epub_rejects_missing_spine_content(tmp_path: Path) -> None:
    missing_spine_item = _OPF.replace(b'href="chapter.xhtml"', b'href="missing.xhtml"')
    with pytest.raises(ApplicationError) as caught:
        parse(make_epub(tmp_path / "missing-spine.epub", opf=missing_spine_item))
    assert caught.value.code == "invalid_epub"
