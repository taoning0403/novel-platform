import secrets
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import select

from novel_platform.infrastructure.database.models import (
    AuthSessionModel,
    RefreshTokenModel,
)


def credential_login_payload(
    credential: str,
    *,
    delivery: str = "body",
    name: str = "阅读设备",
) -> dict[str, Any]:
    return {
        "credential": credential,
        "refresh_token_delivery": delivery,
        "device": {
            "client_instance_id": str(uuid4()),
            "name": name,
            "platform": "web",
            "app_version": "0.8.0-test",
        },
    }


async def create_reader(
    client,
    admin_headers: dict[str, str],
    *,
    display_name: str = "受邀阅读者",
) -> tuple[dict[str, Any], str]:
    response = await client.post(
        "/api/v1/admin/readers",
        headers=admin_headers,
        json={
            "display_name": display_name,
            "admin_note": "集成测试",
            "expires_at": (datetime.now(UTC) + timedelta(days=30)).isoformat(),
            "max_devices": 3,
            "allow_new_devices": True,
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    return body["reader"], body["access_credential"]


def bearer(body: dict[str, Any]) -> dict[str, str]:
    return {"Authorization": f"Bearer {body['access_token']}"}


@pytest.mark.integration
async def test_refresh_requires_matching_device_secret(app_harness) -> None:
    admin = await app_harness.provision_admin()
    _, raw = await create_reader(app_harness.client, admin.headers)

    async with app_harness.new_client() as reader_client:
        logged_in = await reader_client.post(
            "/api/v1/auth/login", json=credential_login_payload(raw)
        )
        assert logged_in.status_code == 200, logged_in.text
        body = logged_in.json()

        # The login client carries the device cookie, so refresh rotates normally.
        rotated = await reader_client.post(
            "/api/v1/auth/refresh", json={"refresh_token": body["refresh_token"]}
        )
        assert rotated.status_code == 200, rotated.text
        new_refresh = rotated.json()["refresh_token"]

        # A stolen refresh token without the device secret gets the uniform 401
        # and must not revoke or rotate the victim session.
        async with app_harness.new_client() as attacker_client:
            stolen = await attacker_client.post(
                "/api/v1/auth/refresh", json={"refresh_token": new_refresh}
            )
        assert stolen.status_code == 401
        assert stolen.json()["error"]["code"] == "invalid_refresh_token"

        still_valid = await reader_client.post(
            "/api/v1/auth/refresh", json={"refresh_token": new_refresh}
        )
        assert still_valid.status_code == 200, still_valid.text
        assert (
            await reader_client.get("/api/v1/auth/me", headers=bearer(still_valid.json()))
        ).status_code == 200

        # A wrong device secret is indistinguishable from an unknown token.
        async with app_harness.new_client() as wrong_device_client:
            wrong_device_client.cookies.set(
                app_harness.settings.auth_device_cookie_name,
                secrets.token_urlsafe(32),
                path="/api/v1/auth",
            )
            wrong = await wrong_device_client.post(
                "/api/v1/auth/refresh",
                json={"refresh_token": still_valid.json()["refresh_token"]},
            )
        assert wrong.status_code == 401
        assert wrong.json()["error"] == stolen.json()["error"]

        assert await app_harness.audit_count("refresh_device_binding_failed") == 2

        # Replay with the correct device secret still revokes the whole session.
        replay = await reader_client.post(
            "/api/v1/auth/refresh", json={"refresh_token": new_refresh}
        )
        assert replay.status_code == 401
        assert replay.json()["error"]["code"] == "refresh_token_reused"
        assert (
            await reader_client.get("/api/v1/auth/me", headers=bearer(still_valid.json()))
        ).status_code == 401


@pytest.mark.integration
async def test_cookie_refresh_origin_fail_closed(app_harness) -> None:
    admin = await app_harness.provision_admin()
    _, raw = await create_reader(app_harness.client, admin.headers)

    async with app_harness.new_client() as client:
        logged_in = await client.post(
            "/api/v1/auth/login", json=credential_login_payload(raw, delivery="cookie")
        )
        assert logged_in.status_code == 200, logged_in.text
        assert "refresh_token" not in logged_in.json()

        missing_origin = await client.post("/api/v1/auth/refresh")
        assert missing_origin.status_code == 403
        assert missing_origin.json()["error"]["code"] == "permission_denied"

        evil_origin = await client.post(
            "/api/v1/auth/refresh", headers={"Origin": "https://evil.example"}
        )
        assert evil_origin.status_code == 403

        allowed = await client.post(
            "/api/v1/auth/refresh", headers={"Origin": "http://localhost:3000"}
        )
        assert allowed.status_code == 200, allowed.text
        rotated = allowed.json()
        assert (await client.get("/api/v1/auth/me", headers=bearer(rotated))).status_code == 200


@pytest.mark.integration
async def test_device_cookie_reissued_with_independent_lifetime_on_login_reuse(
    app_harness,
) -> None:
    admin = await app_harness.provision_admin()
    _, raw = await create_reader(app_harness.client, admin.headers)
    expected_max_age = str(app_harness.settings.auth_device_cookie_ttl_days * 86_400)
    cookie_name = app_harness.settings.auth_device_cookie_name

    async with app_harness.new_client() as client:
        first = await client.post("/api/v1/auth/login", json=credential_login_payload(raw))
        assert first.status_code == 200, first.text
        first_cookie = first.headers["set-cookie"]
        assert f"{cookie_name}=" in first_cookie
        assert f"Max-Age={expected_max_age}" in first_cookie
        first_secret = client.cookies.get(cookie_name)
        assert first_secret

        reused = await client.post(
            "/api/v1/auth/login", json=credential_login_payload(raw, name="复用设备")
        )
        assert reused.status_code == 200, reused.text
        reused_cookie = reused.headers["set-cookie"]
        assert f"{cookie_name}=" in reused_cookie
        assert f"Max-Age={expected_max_age}" in reused_cookie
        assert client.cookies.get(cookie_name) == first_secret


@pytest.mark.integration
async def test_refresh_binding_failure_audits_without_session_revocation(app_harness) -> None:
    admin = await app_harness.provision_admin()
    async with app_harness.new_client() as attacker:
        response = await attacker.post(
            "/api/v1/auth/refresh", json={"refresh_token": admin.refresh_token}
        )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_refresh_token"

    async with app_harness.session_factory() as session:
        auth_session = await session.get(AuthSessionModel, admin.session_id)
        assert auth_session is not None and auth_session.revoked_at is None
        token_rows = await session.scalars(
            select(RefreshTokenModel).where(RefreshTokenModel.session_id == admin.session_id)
        )
        assert all(row.used_at is None for row in token_rows)
    assert await app_harness.audit_count("refresh_device_binding_failed") == 1
