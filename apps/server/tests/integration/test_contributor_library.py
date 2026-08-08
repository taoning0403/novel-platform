from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import func, select

from novel_platform.infrastructure.database.models import (
    BookEditionModel,
    BookModel,
    LibraryImportModel,
    ReadingProgressModel,
    StoredFileModel,
)


async def create_reader_login(
    app_harness,
    admin_headers: dict[str, str],
    *,
    name: str,
    capabilities: list[str],
) -> tuple[dict[str, Any], dict[str, str]]:
    created = await app_harness.client.post(
        "/api/v1/admin/readers",
        headers=admin_headers,
        json={
            "display_name": name,
            "expires_at": (datetime.now(UTC) + timedelta(days=30)).isoformat(),
            "capabilities": capabilities,
        },
    )
    assert created.status_code == 201, created.text
    logged_in = await app_harness.client.post(
        "/api/v1/auth/login",
        json={
            "credential": created.json()["access_credential"],
            "refresh_token_delivery": "body",
            "device": {
                "client_instance_id": str(uuid4()),
                "name": f"{name}的测试设备",
                "platform": "web",
                "app_version": "0.9.0-test",
            },
        },
    )
    assert logged_in.status_code == 200, logged_in.text
    return cast(dict[str, Any], created.json()["reader"]), {
        "Authorization": f"Bearer {logged_in.json()['access_token']}"
    }


async def inspect_txt(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    *,
    operation: str,
    filename: str,
    target_book_id: str | None = None,
    target_edition_id: str | None = None,
) -> httpx.Response:
    data = {"operation": operation, "text_encoding": "auto"}
    if target_book_id is not None:
        data["target_book_id"] = target_book_id
    if target_edition_id is not None:
        data["target_edition_id"] = target_edition_id
    return await client.post(
        "/api/v1/imports/inspect",
        headers=headers,
        data=data,
        files={"file": (filename, f"第一章\n{filename} 正文".encode(), "text/plain")},
    )


async def commit_import(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    import_id: str,
    payload: dict[str, Any],
) -> httpx.Response:
    return await client.post(
        f"/api/v1/imports/{import_id}/commit",
        headers=headers,
        json=payload,
    )


async def create_txt_book(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    *,
    title: str,
) -> dict[str, Any]:
    inspected = await inspect_txt(
        client,
        headers,
        operation="create_book",
        filename=f"{title}.txt",
    )
    assert inspected.status_code == 201, inspected.text
    committed = await commit_import(
        client,
        headers,
        inspected.json()["id"],
        {
            "canonical_title": title,
            "edition_title": f"{title}原文",
            "language": "zh-CN",
            "content_role": "source",
        },
    )
    assert committed.status_code == 200, committed.text
    return cast(dict[str, Any], committed.json())


async def add_txt_edition(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    *,
    book_id: str,
    title: str,
) -> dict[str, Any]:
    inspected = await inspect_txt(
        client,
        headers,
        operation="add_edition",
        filename=f"{title}.txt",
        target_book_id=book_id,
    )
    assert inspected.status_code == 201, inspected.text
    committed = await commit_import(
        client,
        headers,
        inspected.json()["id"],
        {
            "edition_title": title,
            "language": "zh-CN",
            "content_role": "source",
        },
    )
    assert committed.status_code == 200, committed.text
    return cast(dict[str, Any], committed.json())


@pytest.mark.integration
async def test_contributor_upload_attribution_isolation_and_resource_policy(
    app_harness,
    tmp_path: Path,
) -> None:
    client = app_harness.client
    admin = await app_harness.provision_admin()
    reader, reader_headers = await create_reader_login(
        app_harness,
        admin.headers,
        name="只读者",
        capabilities=["library.read"],
    )
    uploader, uploader_headers = await create_reader_login(
        app_harness,
        admin.headers,
        name="上传者 B",
        capabilities=["library.read", "library.upload"],
    )
    other_uploader, other_headers = await create_reader_login(
        app_harness,
        admin.headers,
        name="上传者 D",
        capabilities=["library.read", "library.upload"],
    )
    _, translator_headers = await create_reader_login(
        app_harness,
        admin.headers,
        name="翻译者 C",
        capabilities=["library.read", "translation.use"],
    )

    for denied_headers in (reader_headers, translator_headers):
        denied = await inspect_txt(
            client,
            denied_headers,
            operation="create_book",
            filename="denied.txt",
        )
        assert denied.status_code == 403
        assert denied.json()["error"]["code"] == "library_capability_required"

    series = await client.post(
        "/api/v1/series",
        headers=admin.headers,
        json={"name": "管理员系列"},
    )
    assert series.status_code == 201
    restricted = await inspect_txt(
        client,
        uploader_headers,
        operation="create_book",
        filename="受限字段.txt",
    )
    assert restricted.status_code == 201
    restricted_id = restricted.json()["id"]
    forbidden_series = await commit_import(
        client,
        uploader_headers,
        restricted_id,
        {
            "series_id": series.json()["id"],
            "canonical_title": "受限字段",
            "edition_title": "受限字段原文",
            "language": "zh-CN",
            "content_role": "source",
        },
    )
    assert forbidden_series.status_code == 403
    forbidden_draft = await commit_import(
        client,
        uploader_headers,
        restricted_id,
        {
            "canonical_title": "受限字段",
            "edition_title": "受限字段原文",
            "language": "zh-CN",
            "content_role": "source",
            "edition_status": "draft",
        },
    )
    assert forbidden_draft.status_code == 403
    assert (
        await client.delete(f"/api/v1/imports/{restricted_id}", headers=uploader_headers)
    ).status_code == 204

    inspected = await inspect_txt(
        client,
        uploader_headers,
        operation="create_book",
        filename="贡献作品.txt",
    )
    assert inspected.status_code == 201, inspected.text
    import_id = inspected.json()["id"]
    assert (
        await client.get(f"/api/v1/imports/{import_id}", headers=other_headers)
    ).status_code == 404
    cross_commit = await commit_import(
        client,
        other_headers,
        import_id,
        {
            "canonical_title": "越权提交",
            "edition_title": "越权版本",
            "language": "zh-CN",
            "content_role": "source",
        },
    )
    assert cross_commit.status_code == 404

    committed = await commit_import(
        client,
        uploader_headers,
        import_id,
        {
            "canonical_title": "贡献作品",
            "edition_title": "贡献原文",
            "language": "zh-CN",
            "content_role": "source",
        },
    )
    assert committed.status_code == 200, committed.text
    contribution = committed.json()
    book = contribution["book"]
    edition = contribution["edition"]
    for resource in (book, edition):
        assert resource["contributor"] == {"display_name": "上传者 B"}
        assert resource["can_edit"] is True
        assert resource["can_delete"] is True
        assert "created_by_user_id" not in str(resource)
        assert uploader["credential"]["hint"] not in str(resource)
    assert book["can_upload_edition"] is True

    async with app_harness.session_factory() as session:
        stored_book = await session.get(BookModel, UUID(book["id"]))
        stored_edition = await session.get(BookEditionModel, UUID(edition["id"]))
        stored_import = await session.get(LibraryImportModel, UUID(import_id))
        stored_files = list(
            (
                await session.scalars(
                    select(StoredFileModel).where(
                        StoredFileModel.created_by_user_id == UUID(uploader["id"])
                    )
                )
            ).all()
        )
        assert stored_book is not None and stored_edition is not None and stored_import is not None
        assert stored_book.owner_user_id == admin.user_id
        assert stored_book.created_by_user_id == UUID(uploader["id"])
        assert stored_edition.created_by_user_id == UUID(uploader["id"])
        assert stored_import.requested_by_user_id == UUID(uploader["id"])
        assert stored_files and all(item.owner_user_id == admin.user_id for item in stored_files)

    own_update = await client.patch(
        f"/api/v1/books/{book['id']}",
        headers=uploader_headers,
        json={"canonical_title": "贡献作品-修订"},
    )
    assert own_update.status_code == 200
    forbidden_publish = await client.patch(
        f"/api/v1/books/{book['id']}/editions/{edition['id']}",
        headers=uploader_headers,
        json={"status": "archived"},
    )
    assert forbidden_publish.status_code == 403
    assert forbidden_publish.json()["error"]["code"] == "contributor_field_forbidden"

    admin_book = await create_txt_book(client, admin.headers, title="管理员作品")
    admin_book_id = admin_book["book"]["id"]
    admin_edition_id = admin_book["edition"]["id"]
    assert (
        await client.patch(
            f"/api/v1/books/{admin_book_id}",
            headers=uploader_headers,
            json={"canonical_title": "越权修改"},
        )
    ).status_code == 403
    replace_admin = await inspect_txt(
        client,
        uploader_headers,
        operation="replace_edition_file",
        filename="replace-admin.txt",
        target_book_id=admin_book_id,
        target_edition_id=admin_edition_id,
    )
    assert replace_admin.status_code == 403

    uploaded_to_admin = await add_txt_edition(
        client,
        uploader_headers,
        book_id=admin_book_id,
        title="B 的附加版本",
    )
    own_edition_id = uploaded_to_admin["edition"]["id"]
    replacement = await inspect_txt(
        client,
        uploader_headers,
        operation="replace_edition_file",
        filename="B 的替换版本.txt",
        target_book_id=admin_book_id,
        target_edition_id=own_edition_id,
    )
    assert replacement.status_code == 201, replacement.text
    replaced = await commit_import(client, uploader_headers, replacement.json()["id"], {})
    assert replaced.status_code == 200, replaced.text
    assert replaced.json()["edition"]["current_file"]["revision"] == 2

    opened = await client.post(
        f"/api/v1/editions/{own_edition_id}/reader/open",
        headers=reader_headers,
    )
    assert opened.status_code == 200, opened.text
    preferred = await client.patch(
        f"/api/v1/books/{admin_book_id}/preferences",
        headers=reader_headers,
        json={"preferred_edition_id": own_edition_id},
    )
    assert preferred.status_code == 200
    deleted_edition = await client.delete(
        f"/api/v1/books/{admin_book_id}/editions/{own_edition_id}",
        headers=uploader_headers,
    )
    assert deleted_edition.status_code == 204, deleted_edition.text
    cleared = await client.get(
        f"/api/v1/books/{admin_book_id}/preferences",
        headers=reader_headers,
    )
    assert cleared.json()["preferred_edition_id"] is None
    async with app_harness.session_factory() as session:
        progress_count = await session.scalar(
            select(func.count(ReadingProgressModel.edition_id)).where(
                ReadingProgressModel.edition_id == UUID(own_edition_id)
            )
        )
        assert progress_count == 0

    other_contribution = await add_txt_edition(
        client,
        other_headers,
        book_id=book["id"],
        title="D 的跨贡献版本",
    )
    refreshed = await client.get(f"/api/v1/books/{book['id']}", headers=uploader_headers)
    assert refreshed.json()["can_delete"] is False
    conflict = await client.delete(
        f"/api/v1/books/{book['id']}",
        headers=uploader_headers,
    )
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "book_contains_other_contributions"
    assert (
        await client.delete(
            f"/api/v1/books/{book['id']}/editions/{other_contribution['edition']['id']}",
            headers=other_headers,
        )
    ).status_code == 204
    assert (
        await client.delete(f"/api/v1/books/{book['id']}", headers=uploader_headers)
    ).status_code == 204
    assert not any(
        path.name in {item.storage_key for item in stored_files}
        for path in (tmp_path / "library" / "files").rglob("*")
        if path.is_file()
    )
    assert reader["id"] != other_uploader["id"]
