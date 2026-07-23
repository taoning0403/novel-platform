import asyncio
import base64
import io
import zipfile
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import uuid4

import httpx
import pytest

_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


def headers(login_result: dict[str, Any]) -> dict[str, str]:
    return {"Authorization": f"Bearer {login_result['access_token']}"}


async def create_reader_and_login(
    app_harness,
    admin_headers: dict[str, str],
    *,
    name: str,
    client: httpx.AsyncClient,
) -> tuple[dict[str, Any], dict[str, Any], str]:
    created = await app_harness.client.post(
        "/api/v1/admin/readers",
        headers=admin_headers,
        json={
            "display_name": name,
            "admin_note": "共享馆藏测试",
            "expires_at": (datetime.now(UTC) + timedelta(days=30)).isoformat(),
            "max_devices": 3,
            "allow_new_devices": True,
            "capabilities": ["library.read"],
        },
    )
    assert created.status_code == 201, created.text
    raw = created.json()["access_credential"]
    logged_in = await client.post(
        "/api/v1/auth/login",
        json={
            "credential": raw,
            "refresh_token_delivery": "body",
            "device": {
                "client_instance_id": str(uuid4()),
                "name": f"{name}的设备",
                "platform": "web",
                "app_version": "0.6.0-test",
            },
        },
    )
    assert logged_in.status_code == 200, logged_in.text
    return created.json()["reader"], cast(dict[str, Any], logged_in.json()), raw


async def import_book(
    client: httpx.AsyncClient,
    auth: dict[str, str],
    *,
    filename: str,
    content: bytes,
    title: str,
    series_id: str | None = None,
) -> dict[str, Any]:
    inspected = await client.post(
        "/api/v1/imports/inspect",
        headers=auth,
        data={"operation": "create_book", "text_encoding": "auto"},
        files={"file": (filename, content, "application/octet-stream")},
    )
    assert inspected.status_code == 201, inspected.text
    committed = await client.post(
        f"/api/v1/imports/{inspected.json()['id']}/commit",
        headers=auth,
        json={
            "series_id": series_id,
            "canonical_title": title,
            "edition_title": title,
            "language": "zh-CN",
            "content_role": "source",
            "set_preferred": True,
        },
    )
    assert committed.status_code == 200, committed.text
    return cast(dict[str, Any], committed.json())


def epub_bytes() -> bytes:
    output = io.BytesIO()
    container = """<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
      <rootfiles><rootfile full-path="OPS/book.opf"
        media-type="application/oebps-package+xml"/></rootfiles>
    </container>"""
    opf = """<package xmlns="http://www.idpf.org/2007/opf" version="3.0">
      <metadata><title>Reader EPUB</title><language>ja</language></metadata>
      <manifest>
        <item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>
        <item id="c1" href="one.xhtml" media-type="application/xhtml+xml"/>
        <item id="c2" href="two.xhtml" media-type="application/xhtml+xml"/>
        <item id="image" href="image.png" media-type="image/png"/>
      </manifest>
      <spine><itemref idref="c1"/><itemref idref="c2"/></spine>
    </package>"""
    nav = """<html xmlns="http://www.w3.org/1999/xhtml"><body><nav><ol>
      <li><a href="one.xhtml">第一章</a></li><li><a href="two.xhtml">第二章</a></li>
    </ol></nav></body></html>"""
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("mimetype", "application/epub+zip", zipfile.ZIP_STORED)
        archive.writestr("META-INF/container.xml", container)
        archive.writestr("OPS/book.opf", opf)
        archive.writestr("OPS/nav.xhtml", nav)
        archive.writestr(
            "OPS/one.xhtml",
            """<html><body><script>steal()</script><h1 onclick="steal()">第一章</h1>
            <p>安全正文<img src="image.png" onerror="steal()" /></p></body></html>""",
        )
        archive.writestr("OPS/two.xhtml", "<html><body><p>第二章正文</p></body></html>")
        archive.writestr("OPS/image.png", _PNG)
    return output.getvalue()


@pytest.mark.integration
async def test_shared_library_reader_projection_private_state_and_rbac(app_harness) -> None:
    client = app_harness.client
    admin = await app_harness.provision_admin()
    admin_headers = admin.headers
    async with (
        app_harness.new_client() as reader_a_client,
        app_harness.new_client() as reader_a_second_device,
        app_harness.new_client() as reader_b_client,
    ):
        reader_a, reader_a_login, reader_a_raw = await create_reader_and_login(
            app_harness,
            admin_headers,
            name="阅读者 A",
            client=reader_a_client,
        )
        reader_b, reader_b_login, _ = await create_reader_and_login(
            app_harness,
            admin_headers,
            name="阅读者 B",
            client=reader_b_client,
        )
        reader_a_headers = headers(reader_a_login)
        reader_b_headers = headers(reader_b_login)

        second_login = await reader_a_second_device.post(
            "/api/v1/auth/login",
            json={
                "credential": reader_a_raw,
                "refresh_token_delivery": "body",
                "device": {
                    "client_instance_id": str(uuid4()),
                    "name": "阅读者 A 的第二设备",
                    "platform": "web",
                    "app_version": "0.6.0-test",
                },
            },
        )
        assert second_login.status_code == 200
        reader_a_second_headers = headers(second_login.json())

        series_response = await client.post(
            "/api/v1/series",
            headers=admin_headers,
            json={"name": "长篇系列", "description": "管理员维护的共享系列"},
        )
        assert series_response.status_code == 201
        series = series_response.json()
        first = await import_book(
            client,
            admin_headers,
            filename="第一卷.epub",
            content=epub_bytes(),
            title="第一卷",
            series_id=series["id"],
        )
        second = await import_book(
            client,
            admin_headers,
            filename="第二卷.txt",
            content="第一章\n第二卷正文\n\n第二段".encode(),
            title="第二卷",
            series_id=series["id"],
        )

        hidden_book = await client.post(
            "/api/v1/books",
            headers=admin_headers,
            json={"canonical_title": "仅草稿图书"},
        )
        assert hidden_book.status_code == 201
        hidden_edition = await client.post(
            f"/api/v1/books/{hidden_book.json()['id']}/editions",
            headers=admin_headers,
            json={
                "title": "未发布草稿",
                "language": "zh-CN",
                "content_role": "source",
                "creation_method": "uploaded",
                "status": "draft",
            },
        )
        assert hidden_edition.status_code == 201
        hidden_series = await client.post(
            "/api/v1/series", headers=admin_headers, json={"name": "空白系列"}
        )
        await client.post(
            f"/api/v1/series/{hidden_series.json()['id']}/books/{hidden_book.json()['id']}",
            headers=admin_headers,
        )
        draft_on_visible_book = await client.post(
            f"/api/v1/books/{first['book']['id']}/editions",
            headers=admin_headers,
            json={
                "title": "内部草稿",
                "language": "zh-CN",
                "content_role": "translation",
                "translation_origin": "human",
                "creation_method": "edited",
                "status": "draft",
            },
        )
        assert draft_on_visible_book.status_code == 201
        pending_import = await client.post(
            "/api/v1/imports/inspect",
            headers=admin_headers,
            data={"operation": "create_book", "text_encoding": "auto"},
            files={"file": ("未提交.txt", "未完成导入".encode(), "text/plain")},
        )
        assert pending_import.status_code == 201

        books = await reader_a_client.get("/api/v1/books", headers=reader_a_headers)
        assert books.status_code == 200
        assert {book["canonical_title"] for book in books.json()} == {"第一卷", "第二卷"}
        assert all("owner_user_id" not in book for book in books.json())
        series_list = await reader_a_client.get("/api/v1/series", headers=reader_a_headers)
        assert [item["name"] for item in series_list.json()] == ["长篇系列"]
        series_detail = await reader_a_client.get(
            f"/api/v1/series/{series['id']}", headers=reader_a_headers
        )
        assert [book["canonical_title"] for book in series_detail.json()["books"]] == [
            "第一卷",
            "第二卷",
        ]
        assert (
            await reader_a_client.get(
                f"/api/v1/series/{hidden_series.json()['id']}", headers=reader_a_headers
            )
        ).status_code == 404

        first_detail = await reader_a_client.get(
            f"/api/v1/books/{first['book']['id']}", headers=reader_a_headers
        )
        assert first_detail.status_code == 200
        assert [edition["id"] for edition in first_detail.json()["editions"]] == [
            first["edition"]["id"]
        ]
        assert first_detail.json()["editions"][0]["current_file"]["download_url"] is None
        serialized = first_detail.text
        for forbidden in (
            "owner_user_id",
            "storage_key",
            "sha256",
            "/data/library",
        ):
            assert forbidden not in serialized

        edition_id = first["edition"]["id"]
        reader_open_a, reader_open_second = await asyncio.gather(
            reader_a_client.post(
                f"/api/v1/editions/{edition_id}/reader/open", headers=reader_a_headers
            ),
            reader_a_second_device.post(
                f"/api/v1/editions/{edition_id}/reader/open",
                headers=reader_a_second_headers,
            ),
        )
        assert reader_open_a.status_code == reader_open_second.status_code == 200
        opened = reader_open_a.json()
        assert opened["progress"]["version"] == 1
        assert [item["title"] for item in opened["publication"]["toc"]] == [
            "第一章",
            "第二章",
        ]
        first_section, second_section = opened["publication"]["sections"]
        section = await reader_a_client.get(
            f"/api/v1/editions/{edition_id}/reader/sections/{first_section['id']}",
            headers=reader_a_headers,
        )
        assert section.status_code == 200
        assert "安全正文" in section.json()["html"]
        assert "script" not in section.json()["html"]
        assert "onclick" not in section.json()["html"]
        resource = await reader_a_client.get(
            f"/api/v1/editions/{edition_id}/reader/resources/{section.json()['resource_ids'][0]}",
            headers=reader_a_headers,
        )
        assert resource.status_code == 200
        assert resource.content == _PNG
        assert resource.headers["x-content-type-options"] == "nosniff"

        saved = await reader_a_client.patch(
            f"/api/v1/editions/{edition_id}/reader/progress",
            headers=reader_a_headers,
            json={
                "expected_version": 1,
                "section_id": second_section["id"],
                "block_id": "b00001",
                "section_progress": 0.6,
                "overall_progress": 0.8,
                "edition_file_revision": opened["publication"]["file_revision"],
            },
        )
        assert saved.status_code == 200
        stale = await reader_a_second_device.patch(
            f"/api/v1/editions/{edition_id}/reader/progress",
            headers=reader_a_second_headers,
            json={
                "expected_version": 1,
                "section_id": first_section["id"],
                "block_id": None,
                "section_progress": 0.1,
                "overall_progress": 0.1,
                "edition_file_revision": opened["publication"]["file_revision"],
            },
        )
        assert stale.status_code == 409
        assert stale.json()["error"]["code"] == "reading_progress_conflict"

        reader_b_open = await reader_b_client.post(
            f"/api/v1/editions/{edition_id}/reader/open", headers=reader_b_headers
        )
        assert reader_b_open.json()["progress"]["overall_progress"] == 0
        admin_open = await client.post(
            f"/api/v1/editions/{edition_id}/reader/open", headers=admin_headers
        )
        assert admin_open.json()["progress"]["overall_progress"] == 0

        settings_a = await reader_a_client.patch(
            "/api/v1/reader/settings",
            headers=reader_a_headers,
            json={"font_size": 22, "theme": "sepia"},
        )
        assert settings_a.status_code == 200
        settings_b = await reader_b_client.get("/api/v1/reader/settings", headers=reader_b_headers)
        assert settings_b.json()["font_size"] == 18
        assert settings_b.json()["theme"] == "light"

        preference_a = await reader_a_client.patch(
            f"/api/v1/books/{first['book']['id']}/preferences",
            headers=reader_a_headers,
            json={"preferred_edition_id": edition_id},
        )
        assert preference_a.status_code == 200
        preference_b = await reader_b_client.get(
            f"/api/v1/books/{first['book']['id']}/preferences",
            headers=reader_b_headers,
        )
        assert preference_b.json()["preferred_edition_id"] is None
        recent_a = await reader_a_client.get("/api/v1/reader/recent", headers=reader_a_headers)
        assert recent_a.json()[0]["progress"] == 0.8

        reader_download = await reader_a_client.get(
            f"/api/v1/editions/{edition_id}/file", headers=reader_a_headers
        )
        assert reader_download.status_code == 403
        admin_download = await client.get(
            f"/api/v1/editions/{edition_id}/file", headers=admin_headers
        )
        assert admin_download.status_code == 200
        assert admin_download.content.startswith(b"PK")

        forbidden_requests = [
            reader_a_client.post(
                "/api/v1/books",
                headers=reader_a_headers,
                json={"canonical_title": "越权图书"},
            ),
            reader_a_client.patch(
                f"/api/v1/books/{first['book']['id']}",
                headers=reader_a_headers,
                json={"canonical_title": "越权修改"},
            ),
            reader_a_client.delete(
                f"/api/v1/books/{first['book']['id']}", headers=reader_a_headers
            ),
            reader_a_client.post(
                "/api/v1/series",
                headers=reader_a_headers,
                json={"name": "越权系列"},
            ),
            reader_a_client.get("/api/v1/admin/readers", headers=reader_a_headers),
            reader_a_client.get("/api/v1/admin/site", headers=reader_a_headers),
            reader_a_client.get("/api/v1/admin/audit", headers=reader_a_headers),
            reader_a_client.get("/api/v1/auth/passkeys", headers=reader_a_headers),
        ]
        forbidden = await asyncio.gather(*forbidden_requests)
        assert all(response.status_code == 403 for response in forbidden)

        inspect_denied = await reader_a_client.post(
            "/api/v1/imports/inspect",
            headers=reader_a_headers,
            data={"operation": "create_book", "text_encoding": "auto"},
            files={"file": ("blocked.txt", b"blocked", "text/plain")},
        )
        assert inspect_denied.status_code == 403
        assert reader_a["id"] != reader_b["id"]
        assert second["book"]["id"] != hidden_book.json()["id"]
