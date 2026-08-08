import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import delete, select

from novel_platform.application.auth.admin_service import AdminService
from novel_platform.application.auth.audit_service import AuditService
from novel_platform.application.auth.security import TokenService
from novel_platform.infrastructure.database.models import (
    AdminPasskeyModel,
    AdminRecoveryCredentialModel,
    AuthAuditEventModel,
    ReaderAccessCredentialModel,
    ReaderCredentialCapabilityModel,
)


def credential_login_payload(
    credential: str,
    *,
    client_instance_id: UUID | None = None,
    name: str = "阅读设备",
    delivery: str = "body",
) -> dict[str, Any]:
    return {
        "credential": credential,
        "refresh_token_delivery": delivery,
        "device": {
            "client_instance_id": str(client_instance_id or uuid4()),
            "name": name,
            "platform": "web",
            "app_version": "0.6.0-test",
        },
    }


async def create_reader(
    client: httpx.AsyncClient,
    admin_headers: dict[str, str],
    *,
    display_name: str = "受邀阅读者",
    max_devices: int = 3,
    allow_new_devices: bool = True,
    expires_at: datetime | None = None,
    capabilities: list[str] | None = None,
) -> tuple[dict[str, Any], str]:
    response = await client.post(
        "/api/v1/admin/readers",
        headers=admin_headers,
        json={
            "display_name": display_name,
            "admin_note": "集成测试",
            "expires_at": (expires_at or datetime.now(UTC) + timedelta(days=30)).isoformat(),
            "max_devices": max_devices,
            "allow_new_devices": allow_new_devices,
            "capabilities": capabilities or ["library.read"],
        },
    )
    assert response.status_code == 201, response.text
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    return body["reader"], body["access_credential"]


async def login(
    client: httpx.AsyncClient,
    credential: str,
    *,
    client_instance_id: UUID | None = None,
    name: str = "阅读设备",
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    return await client.post(
        "/api/v1/auth/login",
        json=credential_login_payload(
            credential,
            client_instance_id=client_instance_id,
            name=name,
        ),
        headers=headers,
    )


def bearer(body: dict[str, Any]) -> dict[str, str]:
    return {"Authorization": f"Bearer {body['access_token']}"}


@pytest.mark.integration
async def test_credential_capabilities_are_snapshot_scoped_and_database_authoritative(
    app_harness,
) -> None:
    admin = await app_harness.provision_admin()
    admin_me = await app_harness.client.get("/api/v1/auth/me", headers=admin.headers)
    assert admin_me.status_code == 200
    assert admin_me.json()["user"]["capabilities"] == [
        "library.read",
        "library.upload",
        "translation.use",
    ]

    reader, raw = await create_reader(
        app_harness.client,
        admin.headers,
        capabilities=["library.read", "translation.use"],
    )
    assert reader["credential"]["capabilities"] == ["library.read", "translation.use"]
    logged_in = await login(app_harness.client, raw)
    assert logged_in.status_code == 200, logged_in.text
    reader_headers = bearer(logged_in.json())
    assert logged_in.json()["user"]["capabilities"] == [
        "library.read",
        "translation.use",
    ]

    immutable = await app_harness.client.patch(
        f"/api/v1/admin/readers/{reader['id']}",
        headers=admin.headers,
        json={"capabilities": ["library.read", "library.upload"]},
    )
    assert immutable.status_code == 422

    async with app_harness.session_factory() as session:
        credential = (
            await session.scalars(
                select(ReaderAccessCredentialModel).where(
                    ReaderAccessCredentialModel.user_id == UUID(reader["id"]),
                    ReaderAccessCredentialModel.status == "active",
                )
            )
        ).one()
        await session.execute(
            delete(ReaderCredentialCapabilityModel).where(
                ReaderCredentialCapabilityModel.credential_id == credential.id,
                ReaderCredentialCapabilityModel.capability == "translation.use",
            )
        )
        await session.commit()

    refreshed_me = await app_harness.client.get("/api/v1/auth/me", headers=reader_headers)
    assert refreshed_me.status_code == 200
    assert refreshed_me.json()["user"]["capabilities"] == ["library.read"]

    invalid_sets = (
        ["library.upload"],
        ["library.read", "library.read"],
        ["library.read", "unknown.capability"],
    )
    for capabilities in invalid_sets:
        rejected = await app_harness.client.post(
            "/api/v1/admin/readers",
            headers=admin.headers,
            json={
                "display_name": "无效能力",
                "expires_at": (datetime.now(UTC) + timedelta(days=30)).isoformat(),
                "capabilities": capabilities,
            },
        )
        assert rejected.status_code == 422

    reissued = await app_harness.client.post(
        f"/api/v1/admin/readers/{reader['id']}/credential/reissue",
        headers=admin.headers,
        json={
            "expires_at": (datetime.now(UTC) + timedelta(days=30)).isoformat(),
            "allow_new_devices": True,
            "capabilities": ["library.read", "library.upload"],
        },
    )
    assert reissued.status_code == 200, reissued.text
    assert reissued.json()["reader"]["credential"]["capabilities"] == [
        "library.read",
        "library.upload",
    ]
    new_raw = reissued.json()["access_credential"]
    assert new_raw != raw
    revoked_session = await app_harness.client.get("/api/v1/auth/me", headers=reader_headers)
    assert revoked_session.status_code == 401
    replacement_login = await login(app_harness.client, new_raw)
    assert replacement_login.status_code == 200
    assert replacement_login.json()["user"]["capabilities"] == [
        "library.read",
        "library.upload",
    ]
    audit = await app_harness.client.get(
        f"/api/v1/admin/readers/{reader['id']}/audit",
        headers=admin.headers,
    )
    assert audit.status_code == 200
    assert raw not in audit.text
    assert new_raw not in audit.text


@pytest.mark.integration
async def test_public_boundary_cli_initialization_and_recovery_replay(app_harness) -> None:
    client = app_harness.client
    public_site = await client.get("/api/v1/site")
    assert public_site.status_code == 200
    assert public_site.json()["icp_registration_number"] is None
    assert public_site.json()["icp_registration_url"] is None
    assert public_site.headers["x-robots-tag"] == "noindex, nofollow, noarchive"

    for path in (
        "/api/v1/books",
        f"/api/v1/books/{uuid4()}",
        f"/api/v1/series/{uuid4()}",
        f"/api/v1/editions/{uuid4()}/file",
    ):
        response = await client.get(path)
        assert response.status_code == 401
    assert (await client.get("/api/v1/setup/status")).status_code == 404
    assert (await client.post("/api/v1/setup/initialize", json={})).status_code == 404

    legacy_login = await client.post(
        "/api/v1/auth/login",
        json={
            "username": "admin",
            "password": "old-password",
            "device": {
                "client_instance_id": str(uuid4()),
                "name": "legacy",
                "platform": "web",
            },
        },
    )
    assert legacy_login.status_code == 422
    assert "old-password" not in legacy_login.text

    issued = await app_harness.initialize_admin()
    assert issued.expires_at <= datetime.now(UTC) + timedelta(minutes=16)
    async with app_harness.session_factory() as session:
        row = (await session.scalars(select(AdminRecoveryCredentialModel).limit(1))).one()
        assert row.token_hash != issued.credential
        assert issued.credential not in row.token_hash
        assert row.used_at is None

    recovery_login = await login(client, issued.credential, name="恢复浏览器")
    assert recovery_login.status_code == 200, recovery_login.text
    recovery_body = recovery_login.json()
    assert recovery_body["session"]["recovery_mode"] is True
    assert recovery_login.headers["cache-control"] == "no-store"
    recovery_headers = bearer(recovery_body)
    restricted = await client.get("/api/v1/books", headers=recovery_headers)
    assert restricted.status_code == 403
    assert restricted.json()["error"]["code"] == "recovery_session_restricted"
    options = await client.post(
        "/api/v1/auth/passkeys/registration/options",
        headers={**recovery_headers, "Origin": "http://localhost:3000"},
    )
    assert options.status_code == 200, options.text
    assert options.headers["cache-control"] == "no-store"

    async with app_harness.new_client() as replay_client:
        replay = await login(replay_client, issued.credential)
    assert replay.status_code == 401
    assert replay.json()["error"]["code"] == "invalid_access_credential"


@pytest.mark.integration
async def test_reader_credential_lifecycle_device_limit_and_concurrency(app_harness) -> None:
    admin = await app_harness.provision_admin()
    reader, raw = await create_reader(app_harness.client, admin.headers, max_devices=3)
    assert raw.startswith("npa_")
    assert raw not in str(reader)
    detail = await app_harness.client.get(
        f"/api/v1/admin/readers/{reader['id']}", headers=admin.headers
    )
    assert detail.status_code == 200
    assert raw not in detail.text
    assert detail.json()["credential"]["hint"].startswith("npa_")

    clients = [app_harness.new_client() for _ in range(4)]
    device_instances = [uuid4() for _ in range(4)]
    try:
        logins: list[httpx.Response] = []
        for index, device_client in enumerate(clients[:3], start=1):
            response = await login(
                device_client,
                raw,
                client_instance_id=device_instances[index - 1],
                name=f"设备 {index}",
            )
            assert response.status_code == 200, response.text
            logins.append(response)
        fourth_instance = device_instances[3]
        fourth = await login(
            clients[3],
            raw,
            client_instance_id=fourth_instance,
            name="设备 4",
        )
        assert fourth.status_code == 409
        assert fourth.json()["error"]["code"] == "device_limit_reached"
        assert await app_harness.audit_count("device_limit_exceeded") == 1

        spoofed = await login(
            clients[3],
            raw,
            client_instance_id=device_instances[0],
            name="伪造设备",
        )
        assert spoofed.status_code == 409

        first_again = await login(
            clients[0],
            raw,
            headers={"X-Forwarded-For": "203.0.113.8"},
            name="设备 1 改名",
        )
        assert first_again.status_code == 200
        devices = await app_harness.client.get(
            f"/api/v1/admin/readers/{reader['id']}/devices", headers=admin.headers
        )
        active = [item for item in devices.json() if item["revoked_at"] is None]
        assert len(active) == 3

        shrink = await app_harness.client.patch(
            f"/api/v1/admin/readers/{reader['id']}",
            headers=admin.headers,
            json={"max_devices": 2},
        )
        assert shrink.status_code == 200
        assert (await login(clients[0], raw, name="设备 1")).status_code == 200
        assert (await login(clients[3], raw, name="仍被阻止的设备 4")).status_code == 409
        still_active = (
            await app_harness.client.get(
                f"/api/v1/admin/readers/{reader['id']}/devices", headers=admin.headers
            )
        ).json()
        assert len([item for item in still_active if item["revoked_at"] is None]) == 3
        restore_limit = await app_harness.client.patch(
            f"/api/v1/admin/readers/{reader['id']}",
            headers=admin.headers,
            json={"max_devices": 3},
        )
        assert restore_limit.status_code == 200

        revoked_id = active[-1]["id"]
        revoked = await app_harness.client.post(
            f"/api/v1/admin/readers/{reader['id']}/devices/{revoked_id}/revoke",
            headers=admin.headers,
        )
        assert revoked.status_code == 204
        replacement = await login(
            clients[3], raw, client_instance_id=fourth_instance, name="设备 4"
        )
        assert replacement.status_code == 200, replacement.text
    finally:
        for device_client in clients:
            await device_client.aclose()

    concurrent_reader, concurrent_raw = await create_reader(
        app_harness.client,
        admin.headers,
        display_name="并发上限阅读者",
        max_devices=1,
    )
    async with app_harness.new_client() as first_client, app_harness.new_client() as second_client:
        results = await asyncio.gather(
            login(first_client, concurrent_raw, name="并发 A"),
            login(second_client, concurrent_raw, name="并发 B"),
        )
    assert sorted(response.status_code for response in results) == [200, 409]
    devices = await app_harness.client.get(
        f"/api/v1/admin/readers/{concurrent_reader['id']}/devices", headers=admin.headers
    )
    assert len([item for item in devices.json() if item["revoked_at"] is None]) == 1


@pytest.mark.integration
async def test_reader_suspend_expiry_reissue_and_uniform_failures(app_harness) -> None:
    admin = await app_harness.provision_admin()
    reader, raw = await create_reader(app_harness.client, admin.headers, max_devices=2)
    async with app_harness.new_client() as reader_client:
        logged_in = await login(reader_client, raw)
        assert logged_in.status_code == 200
        reader_headers = bearer(logged_in.json())

        disallow = await app_harness.client.patch(
            f"/api/v1/admin/readers/{reader['id']}",
            headers=admin.headers,
            json={"allow_new_devices": False},
        )
        assert disallow.status_code == 200
        assert (await login(reader_client, raw)).status_code == 200
        async with app_harness.new_client() as unknown_device:
            denied = await login(unknown_device, raw)
        assert denied.status_code == 401
        allow = await app_harness.client.patch(
            f"/api/v1/admin/readers/{reader['id']}",
            headers=admin.headers,
            json={"allow_new_devices": True},
        )
        assert allow.status_code == 200

        suspend = await app_harness.client.post(
            f"/api/v1/admin/readers/{reader['id']}/credential/suspend",
            headers=admin.headers,
        )
        assert suspend.status_code == 204
        assert (
            await reader_client.get("/api/v1/auth/me", headers=reader_headers)
        ).status_code == 401
        suspended_login = await login(reader_client, raw)
        unknown_login = await login(reader_client, f"npa_{'x' * 43}")
        assert suspended_login.status_code == unknown_login.status_code == 401
        assert suspended_login.json()["error"] == unknown_login.json()["error"]

        resume = await app_harness.client.post(
            f"/api/v1/admin/readers/{reader['id']}/credential/resume",
            headers=admin.headers,
        )
        assert resume.status_code == 204
        resumed = await login(reader_client, raw)
        assert resumed.status_code == 200
        devices_before = (
            await app_harness.client.get(
                f"/api/v1/admin/readers/{reader['id']}/devices", headers=admin.headers
            )
        ).json()

        expire = await app_harness.client.patch(
            f"/api/v1/admin/readers/{reader['id']}",
            headers=admin.headers,
            json={"expires_at": (datetime.now(UTC) - timedelta(seconds=1)).isoformat()},
        )
        assert expire.status_code == 200
        assert expire.json()["credential"]["effective_status"] == "expired"
        assert (
            await reader_client.get("/api/v1/auth/me", headers=bearer(resumed.json()))
        ).status_code == 401
        extend = await app_harness.client.patch(
            f"/api/v1/admin/readers/{reader['id']}",
            headers=admin.headers,
            json={"expires_at": (datetime.now(UTC) + timedelta(days=10)).isoformat()},
        )
        assert extend.status_code == 200
        relogin = await login(reader_client, raw)
        assert relogin.status_code == 200
        devices_after = (
            await app_harness.client.get(
                f"/api/v1/admin/readers/{reader['id']}/devices", headers=admin.headers
            )
        ).json()
        assert len(devices_after) == len(devices_before)

        revoke = await app_harness.client.post(
            f"/api/v1/admin/readers/{reader['id']}/credential/revoke",
            headers=admin.headers,
        )
        assert revoke.status_code == 204
        assert (await login(reader_client, raw)).status_code == 401
        reissued = await app_harness.client.post(
            f"/api/v1/admin/readers/{reader['id']}/credential/reissue",
            headers=admin.headers,
            json={
                "expires_at": (datetime.now(UTC) + timedelta(days=20)).isoformat(),
                "max_devices": 2,
                "allow_new_devices": True,
                "capabilities": ["library.read"],
            },
        )
        assert reissued.status_code == 200
        assert reissued.headers["cache-control"] == "no-store"
        assert reissued.json()["reader"]["id"] == reader["id"]
        new_raw = reissued.json()["access_credential"]
        assert new_raw != raw
        assert (await login(reader_client, raw)).status_code == 401
        assert (await login(reader_client, new_raw)).status_code == 200

    async with app_harness.session_factory() as session:
        hashes = list(
            (
                await session.scalars(
                    select(ReaderAccessCredentialModel.token_hash).where(
                        ReaderAccessCredentialModel.user_id == UUID(reader["id"])
                    )
                )
            ).all()
        )
        assert raw not in hashes
        assert new_raw not in hashes


@pytest.mark.integration
@pytest.mark.parametrize("known_credential", [True, False], ids=["known", "unknown"])
async def test_failed_credential_login_rate_limit_is_uniform(
    app_harness, known_credential: bool
) -> None:
    admin = await app_harness.provision_admin()
    if known_credential:
        reader, credential = await create_reader(app_harness.client, admin.headers)
        suspended = await app_harness.client.post(
            f"/api/v1/admin/readers/{reader['id']}/credential/suspend",
            headers=admin.headers,
        )
        assert suspended.status_code == 204
    else:
        credential = f"npa_{'z' * 43}"

    responses = [
        await login(app_harness.client, credential)
        for _ in range(app_harness.settings.auth_login_max_failures + 1)
    ]

    assert [response.status_code for response in responses] == [
        *([401] * (app_harness.settings.auth_login_max_failures - 1)),
        429,
        429,
    ]
    for response in responses[: app_harness.settings.auth_login_max_failures - 1]:
        assert response.json()["error"]["code"] == "invalid_access_credential"
        assert response.json()["error"]["message"] == "访问凭证无效、已过期或当前不可用。"
    for response in responses[app_harness.settings.auth_login_max_failures - 1 :]:
        assert response.json()["error"]["code"] == "login_temporarily_blocked"
        assert response.json()["error"]["message"] == "登录尝试过多，请稍后再试。"
    assert await app_harness.audit_count("login_rate_limited") == 1


@pytest.mark.integration
async def test_audit_cleanup_respects_ninety_day_retention_boundary(app_harness) -> None:
    now = datetime.now(UTC)
    old_event_id = uuid4()
    retained_event_id = uuid4()
    async with app_harness.session_factory() as session:
        session.add_all(
            [
                AuthAuditEventModel(
                    id=old_event_id,
                    event_type="retention_boundary_fixture",
                    outcome="success",
                    created_at=now - timedelta(days=91),
                ),
                AuthAuditEventModel(
                    id=retained_event_id,
                    event_type="retention_boundary_fixture",
                    outcome="success",
                    created_at=now - timedelta(days=89),
                ),
            ]
        )
        await session.commit()

        assert await AuditService(session).cleanup() == 1
        remaining = list(
            (
                await session.scalars(
                    select(AuthAuditEventModel.id).where(
                        AuthAuditEventModel.event_type == "retention_boundary_fixture"
                    )
                )
            ).all()
        )

    assert remaining == [retained_event_id]
    assert await app_harness.audit_count("audit_cleanup_completed") == 1


@pytest.mark.integration
async def test_refresh_rotation_private_session_isolation_and_admin_emergency_controls(
    app_harness,
) -> None:
    admin = await app_harness.provision_admin()
    reader_a, raw_a = await create_reader(
        app_harness.client,
        admin.headers,
        display_name="阅读者 A",
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    reader_b, raw_b = await create_reader(
        app_harness.client, admin.headers, display_name="阅读者 B"
    )
    async with app_harness.new_client() as client_a, app_harness.new_client() as client_b:
        login_a = await login(client_a, raw_a)
        login_b = await login(client_b, raw_b)
        assert login_a.status_code == login_b.status_code == 200
        body_a = login_a.json()
        body_b = login_b.json()
        assert datetime.fromisoformat(body_a["session"]["expires_at"]) <= datetime.now(
            UTC
        ) + timedelta(hours=1, minutes=1)

        sessions_b = await client_b.get("/api/v1/auth/sessions", headers=bearer(body_b))
        target_session = sessions_b.json()[0]["id"]
        cross_session = await client_a.delete(
            f"/api/v1/auth/sessions/{target_session}", headers=bearer(body_a)
        )
        assert cross_session.status_code == 404

        devices_b = await client_b.get("/api/v1/devices", headers=bearer(body_b))
        cross_device = await client_a.post(
            f"/api/v1/devices/{devices_b.json()[0]['id']}/revoke",
            headers=bearer(body_a),
        )
        assert cross_device.status_code == 404

        rotated = await client_a.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": body_a["refresh_token"]},
        )
        assert rotated.status_code == 200
        replay = await client_a.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": body_a["refresh_token"]},
        )
        assert replay.status_code == 401
        assert replay.json()["error"]["code"] == "refresh_token_reused"
        assert (
            await client_a.get("/api/v1/auth/me", headers=bearer(rotated.json()))
        ).status_code == 401

    async with app_harness.session_factory() as session:
        service = AdminService(session, app_harness.settings)
        await service.lock()
    locked = await app_harness.client.get("/api/v1/admin/site", headers=admin.headers)
    assert locked.status_code == 401
    async with app_harness.session_factory() as session:
        service = AdminService(session, app_harness.settings)
        await service.unlock()
        status = await service.status()
        assert status.locked is False
    assert (
        await app_harness.client.get("/api/v1/admin/site", headers=admin.headers)
    ).status_code == 401

    new_admin_session = await app_harness.provision_admin()
    async with app_harness.session_factory() as session:
        issued = await AdminService(session, app_harness.settings).reset_credentials()
    assert (
        await app_harness.client.get("/api/v1/admin/site", headers=new_admin_session.headers)
    ).status_code == 401
    recovery = await login(app_harness.client, issued.credential)
    assert recovery.status_code == 200
    assert recovery.json()["session"]["recovery_mode"] is True
    async with app_harness.session_factory() as session:
        active_passkeys = list(
            (
                await session.scalars(
                    select(AdminPasskeyModel.id).where(AdminPasskeyModel.revoked_at.is_(None))
                )
            ).all()
        )
        assert active_passkeys == []

    assert reader_a["id"] != reader_b["id"]
    assert TokenService(app_harness.settings).hash_access_credential(raw_a) != raw_a
