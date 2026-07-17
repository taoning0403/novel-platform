from typing import Any

import httpx
import pytest


async def auth_headers(app_harness) -> dict[str, str]:
    return (await app_harness.provision_admin()).headers


async def create_book(
    client: httpx.AsyncClient, title: str, headers: dict[str, str]
) -> dict[str, Any]:
    response = await client.post("/api/v1/books", json={"canonical_title": title}, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


async def create_edition(
    client: httpx.AsyncClient,
    book_id: str,
    payload: dict[str, Any],
    headers: dict[str, str],
) -> httpx.Response:
    return await client.post(f"/api/v1/books/{book_id}/editions", json=payload, headers=headers)


@pytest.mark.integration
async def test_admin_edition_workflow(api_client: httpx.AsyncClient, app_harness) -> None:
    assert (await api_client.get("/api/v1/health/live")).json() == {"status": "ok"}
    assert (await api_client.get("/api/v1/health/ready")).json() == {"status": "ok"}
    headers = await auth_headers(app_harness)

    book = await create_book(api_client, "  Example novel  ", headers)
    other_book = await create_book(api_client, "Other novel", headers)
    assert book["canonical_title"] == "Example novel"
    assert book["metadata"] == {}
    assert "owner_user_id" not in book

    source_response = await create_edition(
        api_client,
        book["id"],
        {
            "title": "Japanese source",
            "language": "ja",
            "content_role": "source",
            "translation_origin": None,
            "creation_method": "uploaded",
            "status": "ready",
        },
        headers,
    )
    assert source_response.status_code == 201, source_response.text
    source = source_response.json()

    generated_ai_response = await create_edition(
        api_client,
        book["id"],
        {
            "title": "Generated AI translation",
            "language": "zh-CN",
            "content_role": "translation",
            "translation_origin": "ai",
            "creation_method": "generated",
            "source_edition_id": source["id"],
            "status": "ready",
        },
        headers,
    )
    assert generated_ai_response.status_code == 201, generated_ai_response.text
    generated_ai = generated_ai_response.json()

    independent_editions = []
    for title, origin in (("External AI", "ai"), ("Human translation", "human")):
        response = await create_edition(
            api_client,
            book["id"],
            {
                "title": title,
                "language": "zh-CN",
                "content_role": "translation",
                "translation_origin": origin,
                "creation_method": "uploaded",
                "source_edition_id": None,
                "status": "ready",
            },
            headers,
        )
        assert response.status_code == 201, response.text
        independent_editions.append(response.json())

    mixed_response = await create_edition(
        api_client,
        book["id"],
        {
            "title": "Reviewed translation",
            "language": "zh-CN",
            "content_role": "translation",
            "translation_origin": "mixed",
            "creation_method": "edited",
            "source_edition_id": source["id"],
            "supersedes_edition_id": generated_ai["id"],
            "status": "ready",
        },
        headers,
    )
    assert mixed_response.status_code == 201, mixed_response.text

    independent = independent_editions[0]
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

    other_source_response = await create_edition(
        api_client,
        other_book["id"],
        {
            "title": "Other source",
            "language": "en",
            "content_role": "source",
            "translation_origin": None,
            "creation_method": "uploaded",
        },
        headers,
    )
    other_source = other_source_response.json()
    cross_book = await api_client.patch(
        f"/api/v1/books/{book['id']}/editions/{independent['id']}",
        json={"source_edition_id": other_source["id"]},
        headers=headers,
    )
    assert cross_book.status_code == 409
    assert cross_book.json()["error"]["code"] == "cross_book_edition_reference"

    translation_as_source = await api_client.patch(
        f"/api/v1/books/{book['id']}/editions/{independent['id']}",
        json={"source_edition_id": generated_ai["id"]},
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

    missing_origin = await create_edition(
        api_client,
        book["id"],
        {
            "title": "Invalid translation",
            "language": "zh-CN",
            "content_role": "translation",
            "translation_origin": None,
            "creation_method": "uploaded",
        },
        headers,
    )
    assert missing_origin.status_code == 400
    assert missing_origin.json()["error"]["code"] == "invalid_translation_origin"

    detail = await api_client.get(f"/api/v1/books/{book['id']}", headers=headers)
    assert detail.status_code == 200
    body = detail.json()
    assert body["edition_count"] == 5
    assert body["editions"][0]["content_role"] == "source"

    books = await api_client.get(
        "/api/v1/books", params={"limit": 10, "offset": 0}, headers=headers
    )
    assert books.status_code == 200
    assert {item["canonical_title"] for item in books.json()} == {"Example novel", "Other novel"}
