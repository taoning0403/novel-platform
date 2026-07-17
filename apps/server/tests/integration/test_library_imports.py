import asyncio
import base64
import io
import os
import zipfile
from pathlib import Path
from typing import Any, cast

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


async def inspect_upload(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    *,
    filename: str,
    content: bytes,
    operation: str,
    target_book_id: str | None = None,
    target_edition_id: str | None = None,
    encoding: str = "auto",
) -> httpx.Response:
    data = {"operation": operation, "text_encoding": encoding}
    if target_book_id:
        data["target_book_id"] = target_book_id
    if target_edition_id:
        data["target_edition_id"] = target_edition_id
    return await client.post(
        "/api/v1/imports/inspect",
        headers=headers,
        data=data,
        files={"file": (filename, content, "application/octet-stream")},
    )


async def commit_upload(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    upload_id: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    response = await client.post(
        f"/api/v1/imports/{upload_id}/commit",
        headers=headers,
        json=payload,
    )
    assert response.status_code == 200, response.text
    return cast(dict[str, Any], response.json())


def epub_bytes() -> bytes:
    output = io.BytesIO()
    container = """<container
      xmlns="urn:oasis:names:tc:opendocument:xmlns:container" version="1.0">
      <rootfiles><rootfile full-path="OPS/book.opf"
        media-type="application/oebps-package+xml"/></rootfiles>
    </container>"""
    opf = """<package xmlns="http://www.idpf.org/2007/opf"
      xmlns:dc="http://purl.org/dc/elements/1.1/" version="3.0">
      <metadata><dc:title>Browser Fixture</dc:title>
        <dc:creator>Fixture Author</dc:creator><dc:language>ja</dc:language></metadata>
      <manifest><item id="cover" href="cover.png" media-type="image/png"
        properties="cover-image"/><item id="c1" href="1.xhtml"
        media-type="application/xhtml+xml"/></manifest>
      <spine><itemref idref="c1"/></spine>
    </package>"""
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        archive.writestr("META-INF/container.xml", container)
        archive.writestr("OPS/book.opf", opf)
        archive.writestr("OPS/cover.png", _PNG)
        archive.writestr("OPS/1.xhtml", "<html><body>fixture</body></html>")
    return output.getvalue()


@pytest.mark.integration
async def test_txt_import_revision_relationship_and_transactional_cleanup(
    app_harness, tmp_path: Path
) -> None:
    client = app_harness.client
    admin = await app_harness.provision_admin()
    original_translation = "第一章\n独立 AI 译文".encode()
    inspected = await inspect_upload(
        client,
        admin.headers,
        filename="../独立译文.txt",
        content=original_translation,
        operation="create_book",
    )
    assert inspected.status_code == 201, inspected.text
    preview = inspected.json()
    assert preview["status"] == "ready"
    assert preview["original_filename"] == "独立译文.txt"
    assert "sha256" not in preview
    created = await commit_upload(
        client,
        admin.headers,
        preview["id"],
        {
            "canonical_title": "独立译文作品",
            "canonical_author": "测试作者",
            "edition_title": "AI 译文",
            "language": "zh-CN",
            "content_role": "translation",
            "translation_origin": "ai",
            "set_preferred": True,
        },
    )
    book = created["book"]
    translation = created["edition"]
    assert "owner_user_id" not in book

    source_upload = await inspect_upload(
        client,
        admin.headers,
        filename="原文.txt",
        content="第一章\n原文".encode(),
        operation="add_edition",
        target_book_id=book["id"],
    )
    source = (
        await commit_upload(
            client,
            admin.headers,
            source_upload.json()["id"],
            {
                "edition_title": "原文",
                "language": "ja",
                "content_role": "source",
            },
        )
    )["edition"]
    attached = await client.patch(
        f"/api/v1/books/{book['id']}/editions/{translation['id']}",
        headers=admin.headers,
        json={"source_edition_id": source["id"]},
    )
    assert attached.status_code == 200

    replacement_content = "第一章\n替换后的 AI 译文".encode()
    replacement = await inspect_upload(
        client,
        admin.headers,
        filename="替换版本.txt",
        content=replacement_content,
        operation="replace_edition_file",
        target_book_id=book["id"],
        target_edition_id=translation["id"],
    )
    replaced = await commit_upload(client, admin.headers, replacement.json()["id"], {})
    assert replaced["edition"]["id"] == translation["id"]
    assert replaced["edition"]["current_file"]["revision"] == 2
    preference = await client.get(f"/api/v1/books/{book['id']}/preferences", headers=admin.headers)
    assert preference.json()["preferred_edition_id"] == translation["id"]
    download = await client.get(f"/api/v1/editions/{translation['id']}/file", headers=admin.headers)
    assert download.content == replacement_content

    failed_replacement = await inspect_upload(
        client,
        admin.headers,
        filename="will-fail.txt",
        content=b"new content that must not replace the current file",
        operation="replace_edition_file",
        target_book_id=book["id"],
        target_edition_id=translation["id"],
    )
    engine = create_async_engine(os.environ["TEST_DATABASE_URL"])
    async with engine.connect() as connection:
        temporary_key = await connection.scalar(
            text("SELECT temporary_storage_key FROM library_imports WHERE id=:id"),
            {"id": failed_replacement.json()["id"]},
        )
    await engine.dispose()
    (tmp_path / "library" / "tmp" / temporary_key).unlink()
    failed_commit = await client.post(
        f"/api/v1/imports/{failed_replacement.json()['id']}/commit",
        headers=admin.headers,
        json={},
    )
    assert failed_commit.status_code == 409
    assert failed_commit.json()["error"]["code"] == "file_integrity_error"
    still_current = await client.get(
        f"/api/v1/editions/{translation['id']}/file", headers=admin.headers
    )
    assert still_current.content == replacement_content

    dependency = await client.delete(
        f"/api/v1/books/{book['id']}/editions/{source['id']}", headers=admin.headers
    )
    assert dependency.status_code == 409
    assert dependency.json()["error"]["code"] == "edition_dependency_conflict"
    await client.patch(
        f"/api/v1/books/{book['id']}/editions/{translation['id']}",
        headers=admin.headers,
        json={"source_edition_id": None},
    )
    assert (
        await client.delete(
            f"/api/v1/books/{book['id']}/editions/{source['id']}", headers=admin.headers
        )
    ).status_code == 204
    assert (
        await client.delete(
            f"/api/v1/books/{book['id']}/editions/{translation['id']}",
            headers=admin.headers,
        )
    ).status_code == 204
    assert (
        await client.delete(f"/api/v1/books/{book['id']}", headers=admin.headers)
    ).status_code == 204
    assert not any(path.is_file() for path in (tmp_path / "library" / "files").rglob("*"))


@pytest.mark.integration
async def test_concurrent_replacements_are_serialized_per_edition(app_harness) -> None:
    client = app_harness.client
    admin = await app_harness.provision_admin()
    inspected = await inspect_upload(
        client,
        admin.headers,
        filename="initial.txt",
        content=b"initial revision",
        operation="create_book",
    )
    created = await commit_upload(
        client,
        admin.headers,
        inspected.json()["id"],
        {
            "canonical_title": "Concurrent replacement",
            "edition_title": "Stable Edition",
            "language": "en",
            "content_role": "source",
            "set_preferred": True,
        },
    )
    book_id = created["book"]["id"]
    edition_id = created["edition"]["id"]
    contents = (b"concurrent replacement alpha", b"concurrent replacement beta")
    uploads: list[str] = []
    for index, content in enumerate(contents, start=1):
        replacement = await inspect_upload(
            client,
            admin.headers,
            filename=f"replacement-{index}.txt",
            content=content,
            operation="replace_edition_file",
            target_book_id=book_id,
            target_edition_id=edition_id,
        )
        uploads.append(replacement.json()["id"])
    committed = await asyncio.gather(
        *(commit_upload(client, admin.headers, upload_id, {}) for upload_id in uploads)
    )
    assert {item["upload"]["status"] for item in committed} == {"succeeded"}
    engine = create_async_engine(os.environ["TEST_DATABASE_URL"])
    async with engine.connect() as connection:
        revisions = (
            await connection.execute(
                text(
                    "SELECT revision, is_current FROM edition_files "
                    "WHERE edition_id=:edition_id ORDER BY revision"
                ),
                {"edition_id": edition_id},
            )
        ).all()
    await engine.dispose()
    assert [(row[0], row[1]) for row in revisions] == [
        (1, False),
        (2, False),
        (3, True),
    ]
    download = await client.get(f"/api/v1/editions/{edition_id}/file", headers=admin.headers)
    assert download.content in contents


@pytest.mark.integration
async def test_epub_cover_filters_failures_and_single_owner_storage(app_harness) -> None:
    client = app_harness.client
    admin = await app_harness.provision_admin()
    content = epub_bytes()
    inspected = await inspect_upload(
        client,
        admin.headers,
        filename="fixture.epub",
        content=content,
        operation="create_book",
    )
    assert inspected.status_code == 201
    assert inspected.json()["metadata_preview"]["title"] == "Browser Fixture"
    assert inspected.json()["cover_available"] is True
    cover_preview = await client.get(inspected.json()["cover_preview_url"], headers=admin.headers)
    assert cover_preview.status_code == 200
    created = await commit_upload(
        client,
        admin.headers,
        inspected.json()["id"],
        {
            "canonical_title": "EPUB 作品",
            "canonical_author": "Fixture Author",
            "edition_title": "日文原版",
            "language": "ja",
            "content_role": "source",
            "set_preferred": True,
        },
    )
    cover = await client.get(created["book"]["cover_thumbnail_url"], headers=admin.headers)
    assert cover.status_code == 200
    assert cover.headers["content-type"].startswith("image/jpeg")
    filtered = await client.get(
        "/api/v1/books",
        headers=admin.headers,
        params={"query": "EPUB", "format": "epub", "language": "ja", "page": 1},
    )
    assert [item["id"] for item in filtered.json()] == [created["book"]["id"]]

    fake = await inspect_upload(
        client,
        admin.headers,
        filename="fake.epub",
        content=b"not a zip",
        operation="create_book",
    )
    assert fake.status_code == 422
    upload_id = fake.json()["error"]["details"]["import_id"]
    failed = await client.get(f"/api/v1/imports/{upload_id}", headers=admin.headers)
    assert failed.json()["status"] == "failed"
    assert (
        await client.delete(f"/api/v1/imports/{upload_id}", headers=admin.headers)
    ).status_code == 204

    retryable = await inspect_upload(
        client,
        admin.headers,
        filename="retryable.txt",
        content=b"retryable content",
        operation="create_book",
    )
    rejected = await client.post(
        f"/api/v1/imports/{retryable.json()['id']}/commit",
        headers=admin.headers,
        json={
            "canonical_title": "",
            "edition_title": "",
            "language": "",
            "content_role": "source",
        },
    )
    assert rejected.status_code == 422
    retried = await commit_upload(
        client,
        admin.headers,
        retryable.json()["id"],
        {
            "canonical_title": "Retried metadata",
            "edition_title": "Retried source",
            "language": "en",
            "content_role": "source",
        },
    )
    assert retried["upload"]["error_code"] is None

    engine = create_async_engine(os.environ["TEST_DATABASE_URL"])
    async with engine.connect() as connection:
        owners = await connection.scalar(
            text("SELECT count(DISTINCT owner_user_id) FROM stored_files")
        )
        owner = await connection.scalar(text("SELECT library_owner_user_id FROM site_settings"))
        mismatches = await connection.scalar(
            text("SELECT count(*) FROM stored_files WHERE owner_user_id <> :owner"),
            {"owner": owner},
        )
    await engine.dispose()
    assert owners == 1
    assert mismatches == 0
