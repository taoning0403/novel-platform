import os
import secrets
import tempfile
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import httpx
import pytest_asyncio
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from novel_platform.api.dependencies.storage import get_file_storage
from novel_platform.application.auth.admin_service import AdminService, IssuedRecoveryCredential
from novel_platform.application.auth.security import TokenService
from novel_platform.config import Settings, get_settings
from novel_platform.domain.auth.models import DevicePlatform
from novel_platform.infrastructure.database.base import Base
from novel_platform.infrastructure.database.models import (
    AdminPasskeyModel,
    AdminRecoveryCredentialModel,
    AuthSessionModel,
    DeviceModel,
    RefreshTokenModel,
    SiteSettingsModel,
    UserModel,
)
from novel_platform.infrastructure.database.session import get_session
from novel_platform.infrastructure.storage.local import LocalFileStorage
from novel_platform.main import app


@dataclass(frozen=True, slots=True)
class TestAuth:
    user_id: UUID
    device_id: UUID
    session_id: UUID
    access_token: str
    refresh_token: str
    device_secret: str

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.access_token}"}


@dataclass(slots=True)
class AppHarness:
    client: httpx.AsyncClient
    session_factory: async_sessionmaker[AsyncSession]
    settings: Settings

    def new_client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        )

    async def initialize_admin(self, display_name: str = "站点管理员") -> IssuedRecoveryCredential:
        async with self.session_factory() as session:
            return await AdminService(session, self.settings).initialize(display_name)

    async def provision_admin(self, display_name: str = "站点管理员") -> TestAuth:
        async with self.session_factory() as session:
            site = await session.get(SiteSettingsModel, 1)
            if site is None:
                raise RuntimeError("site settings missing")
            if site.library_owner_user_id is None:
                await AdminService(session, self.settings).initialize(display_name)
                site = await session.get(SiteSettingsModel, 1)
                if site is None or site.library_owner_user_id is None:
                    raise RuntimeError("admin initialization failed")
            admin = await session.get(UserModel, site.library_owner_user_id)
            if admin is None:
                raise RuntimeError("admin missing")
            now = datetime.now(UTC)
            await session.execute(
                update(AdminRecoveryCredentialModel)
                .where(
                    AdminRecoveryCredentialModel.user_id == admin.id,
                    AdminRecoveryCredentialModel.used_at.is_(None),
                    AdminRecoveryCredentialModel.revoked_at.is_(None),
                )
                .values(revoked_at=now)
            )
            passkey = AdminPasskeyModel(
                user_id=admin.id,
                credential_id=secrets.token_bytes(32),
                public_key=secrets.token_bytes(77),
                sign_count=0,
                name="测试 Passkey",
                transports=["internal"],
                device_type="single_device",
                backed_up=False,
                created_at=now,
                updated_at=now,
            )
            session.add(passkey)
            await session.flush()
            tokens = TokenService(self.settings)
            device_secret, device_secret_hash = tokens.new_device_secret()
            device = DeviceModel(
                user_id=admin.id,
                client_instance_id=uuid4(),
                device_secret_hash=device_secret_hash,
                name="管理员测试浏览器",
                platform=DevicePlatform.WEB,
                app_version="0.6.0-test",
                first_authorized_ip="127.0.0.1",
                last_used_ip="127.0.0.1",
                user_agent_summary="integration-test",
                first_seen_at=now,
                last_seen_at=now,
                created_at=now,
                updated_at=now,
            )
            session.add(device)
            await session.flush()
            auth_session = AuthSessionModel(
                user_id=admin.id,
                device_id=device.id,
                passkey_id=passkey.id,
                recovery_mode=False,
                created_at=now,
                last_seen_at=now,
                expires_at=now + timedelta(days=30),
            )
            session.add(auth_session)
            await session.flush()
            raw_refresh, refresh_hash = tokens.new_refresh_token()
            session.add(
                RefreshTokenModel(
                    session_id=auth_session.id,
                    token_hash=refresh_hash,
                    issued_at=now,
                    expires_at=auth_session.expires_at,
                )
            )
            access_token, _ = tokens.issue_access_token(
                user_id=admin.id,
                session_id=auth_session.id,
                device_id=device.id,
                role=admin.role.value,
                session_expires_at=auth_session.expires_at,
                now=now,
            )
            await session.commit()
            return TestAuth(
                user_id=admin.id,
                device_id=device.id,
                session_id=auth_session.id,
                access_token=access_token,
                refresh_token=raw_refresh,
                device_secret=device_secret,
            )

    async def admin_id(self) -> UUID:
        async with self.session_factory() as session:
            site = await session.get(SiteSettingsModel, 1)
            if site is None or site.library_owner_user_id is None:
                raise RuntimeError("admin not initialized")
            return site.library_owner_user_id

    async def audit_count(self, event_type: str) -> int:
        from novel_platform.infrastructure.database.models import AuthAuditEventModel

        async with self.session_factory() as session:
            rows = await session.scalars(
                select(AuthAuditEventModel.id).where(AuthAuditEventModel.event_type == event_type)
            )
            return len(list(rows))


@pytest_asyncio.fixture
async def app_harness(tmp_path: Path) -> AsyncIterator[AppHarness]:
    database_url = os.getenv("TEST_DATABASE_URL")
    if not database_url:
        import pytest

        pytest.skip("TEST_DATABASE_URL is not configured")

    engine = create_async_engine(database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
        await connection.run_sync(Base.metadata.create_all)
    async with factory() as bootstrap_session:
        bootstrap_session.add_all(
            [
                UserModel(
                    id=UUID("00000000-0000-0000-0000-000000000001"),
                    username="__pending_setup__",
                    normalized_username="__pending_setup__",
                    display_name="Pending setup",
                    role="admin",
                    status="pending_setup",
                    password_hash=None,
                ),
                SiteSettingsModel(
                    id=1,
                    site_name="个人数字阅读与藏书整理",
                    purpose_statement="个人非经营性数字阅读与藏书整理。",
                    privacy_statement="仅记录必要的登录与设备安全信息。",
                    default_reader_max_devices=3,
                    audit_retention_days=90,
                ),
            ]
        )
        await bootstrap_session.commit()

    async def override_session() -> AsyncIterator[AsyncSession]:
        async with factory() as session:
            try:
                yield session
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_session] = override_session
    storage = LocalFileStorage(tmp_path / "library")
    previous_temporary_directory = tempfile.tempdir
    tempfile.tempdir = str(storage.temporary_directory)
    app.dependency_overrides[get_file_storage] = lambda: storage
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield AppHarness(client=client, session_factory=factory, settings=get_settings())
    app.dependency_overrides.clear()
    tempfile.tempdir = previous_temporary_directory
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture
async def api_client(app_harness: AppHarness) -> httpx.AsyncClient:
    return app_harness.client
