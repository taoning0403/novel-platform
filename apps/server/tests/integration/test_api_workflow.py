from typing import Any, cast

import httpx
import pytest


async def auth_headers(app_harness) -> dict[str, str]:
    return (await app_harness.provision_admin()).headers


async def inspect_txt(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    *,
    operation: str,
    filename: str,
    target_book_id: str | None = None,
) -> str:
    data = {"operation": operation, "text_encoding": "auto"}
    if target_book_id is not None:
        data["target_book_id"] = target_book_id
    response = await client.post(
        "/api/v1/imports/inspect",
        data=data,
        files={"file": (filename, f"{filename}\n正文".encode(), "text/plain")},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return cast(str, response.json()["id"])


async def create_book(
    client: httpx.AsyncClient,
    title: str,
    headers: dict[str, str],
) -> dict[str, Any]:
    upload_id = await inspect_txt(
        client,
        headers,
        operation="create_book",
        filename=f"{title.strip()}.txt",
    )
    response = await client.post(
        f"/api/v1/imports/{upload_id}/commit",
        json={
            "canonical_title": title,
            "edition_title": "Source",
            "language": "ja",
            "content_role": "source",
        },
        headers=headers,
    )
    assert response.status_code == 200, response.text
    return cast(dict[str, Any], response.json())


async def add_edition(
    client: httpx.AsyncClient,
    book_id: str,
    payload: dict[str, Any],
    headers: dict[str, str],
) -> httpx.Response:
    upload_id = await inspect_txt(
        client,
        headers,
        operation="add_edition",
        filename=f"{payload['edition_title']}.txt",
        target_book_id=book_id,
    )
    return await client.post(
        f"/api/v1/imports/{upload_id}/commit",
        json=payload,
        headers=headers,
    )


@pytest.mark.integration
async def test_admin_file_backed_edition_workflow_and_legacy_removal(
    api_client: httpx.AsyncClient,
    app_harness,
) -> None:
    assert (await api_client.get("/api/v1/health/live")).json() == {"status": "ok"}
    assert (await api_client.get("/api/v1/health/ready")).json() == {"status": "ok"}
    headers = await auth_headers(app_harness)

    legacy_book = await api_client.post(
        "/api/v1/books",
        json={"canonical_title": "No placeholder"},
        headers=headers,
    )
    assert legacy_book.status_code == 405

    book_import = await create_book(api_client, "  Example novel  ", headers)
    other_import = await create_book(api_client, "Other novel", headers)
    book = book_import["book"]
    source = book_import["edition"]
    other_book = other_import["book"]
    other_source = other_import["edition"]
    assert book["canonical_title"] == "Example novel"
    assert book["metadata"]["source_metadata"]["title"] == "Example novel"
    assert book["contributor"] == {"display_name": "站点管理员"}
    assert book["can_upload_edition"] is True
    assert "owner_user_id" not in book

    legacy_edition = await api_client.post(
        f"/api/v1/books/{book['id']}/editions",
        json={
            "title": "No placeholder",
            "language": "en",
            "content_role": "source",
            "creation_method": "uploaded",
        },
        headers=headers,
    )
    assert legacy_edition.status_code == 405

    ai_response = await add_edition(
        api_client,
        book["id"],
        {
            "edition_title": "External AI",
            "language": "zh-CN",
            "content_role": "translation",
            "translation_origin": "ai",
        },
        headers,
    )
    assert ai_response.status_code == 200, ai_response.text
    ai_translation = ai_response.json()["edition"]

    human_response = await add_edition(
        api_client,
        book["id"],
        {
            "edition_title": "Human translation",
            "language": "zh-CN",
            "content_role": "translation",
            "translation_origin": "human",
        },
        headers,
    )
    assert human_response.status_code == 200, human_response.text
    independent = human_response.json()["edition"]

    mixed_response = await add_edition(
        api_client,
        book["id"],
        {
            "edition_title": "Reviewed translation",
            "language": "zh-CN",
            "content_role": "translation",
            "translation_origin": "mixed",
            "source_edition_id": source["id"],
            "supersedes_edition_id": ai_translation["id"],
        },
        headers,
    )
    assert mixed_response.status_code == 200, mixed_response.text

    attached = await api_client.patch(
        f"/api/v1/books/{book['id']}/editions/{independent['id']}",
        json={"source_edition_id": source["id"]},
        headers=headers,
    )
    assert attached.status_code == 200
    assert attached.json()["source_edition_id"] == source["id"]
    detached = await api_client.patch(
        f"/api/v1/books/{book['id']}/editions/{independent['id']}",
        json={"source_edition_id": None, "status": "archived"},
        headers=headers,
    )
    assert detached.status_code == 200
    assert detached.json()["source_edition_id"] is None
    assert detached.json()["status"] == "archived"

    cross_book = await api_client.patch(
        f"/api/v1/books/{book['id']}/editions/{independent['id']}",
        json={"source_edition_id": other_source["id"]},
        headers=headers,
    )
    assert cross_book.status_code == 409
    assert cross_book.json()["error"]["code"] == "cross_book_edition_reference"

    translation_as_source = await api_client.patch(
        f"/api/v1/books/{book['id']}/editions/{independent['id']}",
        json={"source_edition_id": ai_translation["id"]},
        headers=headers,
    )
    assert translation_as_source.status_code == 409
    assert translation_as_source.json()["error"]["code"] == "source_edition_must_be_source"

    self_reference = await api_client.patch(
        f"/api/v1/books/{book['id']}/editions/{independent['id']}",
        json={"supersedes_edition_id": independent["id"]},
        headers=headers,
    )
    assert self_reference.status_code == 400
    assert self_reference.json()["error"]["code"] == "edition_cannot_reference_itself"

    missing_origin = await add_edition(
        api_client,
        book["id"],
        {
            "edition_title": "Invalid translation",
            "language": "zh-CN",
            "content_role": "translation",
            "translation_origin": None,
        },
        headers,
    )
    assert missing_origin.status_code == 400
    assert missing_origin.json()["error"]["code"] == "invalid_translation_origin"

    detail = await api_client.get(f"/api/v1/books/{book['id']}", headers=headers)
    assert detail.status_code == 200
    body = detail.json()
    assert body["edition_count"] == 4
    assert body["editions"][0]["content_role"] == "source"
    assert all(item["current_file"] is not None for item in body["editions"])

    books = await api_client.get(
        "/api/v1/books", params={"limit": 10, "offset": 0}, headers=headers
    )
    assert books.status_code == 200
    assert {item["canonical_title"] for item in books.json()} == {
        "Example novel",
        other_book["canonical_title"],
    }
