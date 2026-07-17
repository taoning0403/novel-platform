import base64
import sys
import zipfile
from pathlib import Path

PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


def write_epub(destination: Path) -> None:
    container = """<container
      xmlns="urn:oasis:names:tc:opendocument:xmlns:container" version="1.0">
      <rootfiles><rootfile full-path="OPS/book.opf"
        media-type="application/oebps-package+xml"/></rootfiles>
    </container>"""
    opf = """<package xmlns="http://www.idpf.org/2007/opf"
      xmlns:dc="http://purl.org/dc/elements/1.1/" version="3.0">
      <metadata><dc:title>验收 EPUB 作品</dc:title>
        <dc:creator>Fixture Author</dc:creator><dc:language>ja</dc:language>
        <dc:description>仓库自行生成的无版权测试内容。</dc:description></metadata>
      <manifest><item id="cover" href="cover.png" media-type="image/png"
        properties="cover-image"/><item id="c1" href="1.xhtml"
        media-type="application/xhtml+xml"/></manifest>
      <spine><itemref idref="c1"/></spine>
    </package>"""
    with zipfile.ZipFile(destination, "w") as archive:
        archive.writestr("mimetype", "application/epub+zip", zipfile.ZIP_STORED)
        archive.writestr("META-INF/container.xml", container)
        archive.writestr("OPS/book.opf", opf)
        archive.writestr("OPS/cover.png", PNG)
        archive.writestr("OPS/1.xhtml", "<html><body>acceptance fixture</body></html>")


def write_unsafe_epub(destination: Path) -> None:
    with zipfile.ZipFile(destination, "w") as archive:
        archive.writestr("mimetype", "application/epub+zip", zipfile.ZIP_STORED)
        archive.writestr("../outside.txt", "unsafe")


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: generate_library_fixtures.py OUTPUT_DIRECTORY")
    output = Path(sys.argv[1])
    output.mkdir(parents=True, exist_ok=True)
    write_epub(output / "acceptance.epub")
    (output / "independent-ai.txt").write_text("第一章\n独立 AI 译文", encoding="utf-8")
    (output / "source.txt").write_text("第一章\n后补原文", encoding="utf-8")
    (output / "replacement.txt").write_text("第一章\n替换后的独立 AI 译文", encoding="utf-8")
    (output / "encoded-cp932.txt").write_bytes("第一章\n日本語の本文".encode("cp932"))
    (output / "fake.epub").write_bytes(b"not a zip")
    write_unsafe_epub(output / "unsafe.epub")


if __name__ == "__main__":
    main()
