import os
import subprocess
import sys
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from novel_platform.application.auth.admin_service import AdminService
from novel_platform.application.auth.migration_service import AuthMigrationService
from novel_platform.application.errors import ApplicationError
from novel_platform.config import Settings
from novel_platform.infrastructure.storage.local import LocalFileStorage


def run_alembic(database_url: str, *arguments: str) -> None:
    executable = Path(sys.executable).parent / "alembic"
    environment = {**os.environ, "DATABASE_URL": database_url}
    subprocess.run(
        [str(executable), *arguments],
        check=True,
        cwd=Path(__file__).parents[2],
        env=environment,
        capture_output=True,
        text=True,
    )


async def create_migration_database(base_url: str) -> tuple[str, URL, str]:
    parsed = make_url(base_url)
    database_name = f"novel_platform_migration_{uuid4().hex}"
    admin_url = parsed.set(database="postgres")
    engine = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
    async with engine.connect() as connection:
        await connection.execute(text(f'CREATE DATABASE "{database_name}"'))
    await engine.dispose()
    return (
        database_name,
        admin_url,
        parsed.set(database=database_name).render_as_string(hide_password=False),
    )


async def drop_migration_database(database_name: str, admin_url: URL) -> None:
    engine = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
    async with engine.connect() as connection:
        await connection.execute(text(f'DROP DATABASE IF EXISTS "{database_name}" WITH (FORCE)'))
    await engine.dispose()


@pytest.mark.integration
async def test_empty_database_upgrade_and_cli_only_admin_initialization(tmp_path: Path) -> None:
    base_url = os.getenv("TEST_DATABASE_URL")
    if not base_url:
        pytest.skip("TEST_DATABASE_URL is not configured")
    database_name, admin_url, database_url = await create_migration_database(base_url)
    try:
        run_alembic(database_url, "upgrade", "head")
        engine = create_async_engine(database_url)
        factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        async with engine.connect() as connection:
            revision = await connection.scalar(text("SELECT version_num FROM alembic_version"))
            tables = {
                name: await connection.scalar(text(f"SELECT to_regclass('public.{name}')"))
                for name in (
                    "site_settings",
                    "reader_access_credentials",
                    "admin_recovery_credentials",
                    "admin_passkeys",
                    "webauthn_challenges",
                )
            }
            site = (
                (
                    await connection.execute(
                        text(
                            "SELECT site_name, icp_registration_number, "
                            "default_reader_max_devices, audit_retention_days, "
                            "library_owner_user_id FROM site_settings"
                        )
                    )
                )
                .mappings()
                .one()
            )
        assert revision == "20260715_0005"
        assert all(value is not None for value in tables.values())
        assert site["site_name"] == "个人数字阅读与藏书整理"
        assert site["icp_registration_number"] is None
        assert site["default_reader_max_devices"] == 3
        assert site["audit_retention_days"] == 90
        assert site["library_owner_user_id"] is None

        settings = Settings(database_url=database_url)
        async with factory() as session:
            issued = await AdminService(session, settings).initialize("唯一管理员")
        async with engine.connect() as connection:
            initialized = (
                (
                    await connection.execute(
                        text(
                            "SELECT u.id, u.role, u.status, u.password_hash, "
                            "s.library_owner_user_id, s.migration_completed_at, "
                            "r.token_hash, r.used_at "
                            "FROM users u JOIN site_settings s ON s.library_owner_user_id=u.id "
                            "JOIN admin_recovery_credentials r ON r.user_id=u.id"
                        )
                    )
                )
                .mappings()
                .one()
            )
        assert initialized["id"] == UUID("00000000-0000-0000-0000-000000000001")
        assert initialized["role"] == "admin"
        assert initialized["status"] == "active"
        assert initialized["password_hash"] is None
        assert initialized["library_owner_user_id"] == initialized["id"]
        assert initialized["migration_completed_at"] is not None
        assert initialized["token_hash"] != issued.credential
        assert issued.credential not in initialized["token_hash"]
        assert initialized["used_at"] is None

        storage = LocalFileStorage(tmp_path / "library")
        storage.initialize()
        temporary = storage.write_temporary_bytes(b"integrity-audit", max_bytes=1024)
        storage_key = storage.commit_temporary(temporary.key)
        async with factory() as session:
            await session.execute(
                text(
                    "INSERT INTO stored_files "
                    "(id, owner_user_id, storage_key, original_filename, media_type, "
                    "file_format, purpose, size_bytes, sha256) VALUES "
                    "('70000000-0000-0000-0000-000000000050', :owner, :key, "
                    "'audit.txt', 'text/plain', 'txt', 'edition_source', :size, :sha)"
                ),
                {
                    "owner": initialized["id"],
                    "key": storage_key,
                    "size": temporary.size_bytes,
                    "sha": temporary.sha256,
                },
            )
            await session.commit()
            report = await AuthMigrationService(session).integrity_audit(storage)
            assert report.consistent is True
            assert report.database_permanent_files == 1
            assert report.physical_permanent_files == 1
        storage.delete_file(storage_key)
        async with factory() as session:
            report = await AuthMigrationService(session).integrity_audit(storage)
            assert report.consistent is False
            assert report.missing_permanent_files == 1
        await engine.dispose()
    finally:
        await drop_migration_database(database_name, admin_url)


@pytest.mark.integration
async def test_v040_explicit_multi_owner_conversion_preserves_ids_and_private_state() -> None:
    base_url = os.getenv("TEST_DATABASE_URL")
    if not base_url:
        pytest.skip("TEST_DATABASE_URL is not configured")
    database_name, admin_url, database_url = await create_migration_database(base_url)
    target_admin = UUID("00000000-0000-0000-0000-000000000001")
    other_admin = UUID("10000000-0000-0000-0000-000000000001")
    reader = UUID("10000000-0000-0000-0000-000000000002")
    device = UUID("20000000-0000-0000-0000-000000000001")
    auth_session = UUID("30000000-0000-0000-0000-000000000001")
    refresh = UUID("40000000-0000-0000-0000-000000000001")
    book = UUID("50000000-0000-0000-0000-000000000001")
    source = UUID("60000000-0000-0000-0000-000000000001")
    translation = UUID("60000000-0000-0000-0000-000000000002")
    successor = UUID("60000000-0000-0000-0000-000000000003")
    series = UUID("90000000-0000-0000-0000-000000000001")
    try:
        run_alembic(database_url, "upgrade", "20260714_0004")
        engine = create_async_engine(database_url)
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "UPDATE users SET username='target-admin', "
                    "normalized_username='target-admin', display_name='Target Admin', "
                    "role='admin', status='active', password_hash='legacy-target-hash' "
                    "WHERE id=:target"
                ),
                {"target": target_admin},
            )
            await connection.execute(
                text(
                    "INSERT INTO users "
                    "(id, username, normalized_username, display_name, role, status, "
                    "password_hash) "
                    "VALUES (:other, 'other-admin', 'other-admin', 'Other Admin', "
                    "'admin', 'active', 'legacy-other-hash'), "
                    "(:reader, 'legacy-reader', 'legacy-reader', 'Legacy Reader', "
                    "'member', 'active', 'legacy-reader-hash')"
                ),
                {"other": other_admin, "reader": reader},
            )
            await connection.execute(
                text(
                    "INSERT INTO devices "
                    "(id, user_id, client_instance_id, name, platform, app_version) VALUES "
                    "(:id, :reader, '20000000-0000-0000-0000-000000000002', "
                    "'Legacy Device', 'web', '0.4.0')"
                ),
                {"id": device, "reader": reader},
            )
            await connection.execute(
                text(
                    "INSERT INTO auth_sessions (id, user_id, device_id, expires_at) "
                    "VALUES (:id, :reader, :device, now() + interval '30 days')"
                ),
                {"id": auth_session, "reader": reader, "device": device},
            )
            await connection.execute(
                text(
                    "INSERT INTO refresh_tokens (id, session_id, token_hash, expires_at) "
                    "VALUES (:id, :session, :hash, now() + interval '30 days')"
                ),
                {"id": refresh, "session": auth_session, "hash": "a" * 64},
            )
            await connection.execute(
                text(
                    "INSERT INTO books (id, owner_user_id, canonical_title, metadata) "
                    "VALUES (:book, :other, 'Preserved Book', '{}'::jsonb)"
                ),
                {"book": book, "other": other_admin},
            )
            await connection.execute(
                text(
                    "INSERT INTO book_editions "
                    "(id, book_id, title, language, content_role, translation_origin, "
                    "creation_method, status, metadata) VALUES "
                    "(:source, :book, 'Source', 'ja', 'source', NULL, 'uploaded', "
                    "'ready', '{}'::jsonb), "
                    "(:translation, :book, 'Translation', 'zh-CN', 'translation', "
                    "'human', 'uploaded', 'ready', '{}'::jsonb), "
                    "(:successor, :book, 'Successor', 'zh-CN', 'translation', "
                    "'mixed', 'edited', 'draft', '{}'::jsonb)"
                ),
                {
                    "source": source,
                    "translation": translation,
                    "successor": successor,
                    "book": book,
                },
            )
            await connection.execute(
                text(
                    "UPDATE book_editions SET source_edition_id=:source "
                    "WHERE id IN (:translation, :successor)"
                ),
                {
                    "source": source,
                    "translation": translation,
                    "successor": successor,
                },
            )
            await connection.execute(
                text(
                    "UPDATE book_editions SET supersedes_edition_id=:translation "
                    "WHERE id=:successor"
                ),
                {"translation": translation, "successor": successor},
            )
            await connection.execute(
                text(
                    "INSERT INTO stored_files "
                    "(id, owner_user_id, storage_key, original_filename, media_type, "
                    "file_format, purpose, size_bytes, sha256) VALUES "
                    "('70000000-0000-0000-0000-000000000001', :reader, :key, "
                    "'legacy.epub', 'application/epub+zip', 'epub', 'edition_source', 12, :sha)"
                ),
                {"reader": reader, "key": "b" * 64, "sha": "c" * 64},
            )
            await connection.execute(
                text(
                    "INSERT INTO edition_files "
                    "(id, edition_id, stored_file_id, revision, is_current, metadata) VALUES "
                    "('80000000-0000-0000-0000-000000000001', :source, "
                    "'70000000-0000-0000-0000-000000000001', 1, true, '{}'::jsonb)"
                ),
                {"source": source},
            )
            await connection.execute(
                text(
                    "INSERT INTO book_series (id, owner_user_id, name) "
                    "VALUES (:series, :reader, 'Preserved Series')"
                ),
                {"series": series, "reader": reader},
            )
            await connection.execute(
                text(
                    "INSERT INTO series_memberships (series_id, book_id, position) "
                    "VALUES (:series, :book, 1)"
                ),
                {"series": series, "book": book},
            )
            await connection.execute(
                text(
                    "INSERT INTO user_book_preferences "
                    "(user_id, book_id, preferred_edition_id, last_opened_edition_id) "
                    "VALUES (:reader, :book, :source, :translation)"
                ),
                {
                    "reader": reader,
                    "book": book,
                    "source": source,
                    "translation": translation,
                },
            )
            await connection.execute(
                text(
                    "INSERT INTO reader_settings (user_id, font_size, theme) "
                    "VALUES (:reader, 21, 'sepia')"
                ),
                {"reader": reader},
            )
            await connection.execute(
                text(
                    "INSERT INTO reading_progresses "
                    "(user_id, edition_id, status, section_id, overall_progress, "
                    "edition_file_revision, version, updated_device_id) VALUES "
                    "(:reader, :source, 'reading', 's00001', 0.42, 1, 7, :device)"
                ),
                {"reader": reader, "source": source, "device": device},
            )
        await engine.dispose()

        run_alembic(database_url, "upgrade", "head")
        engine = create_async_engine(database_url)
        factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        async with factory() as session:
            migration = AuthMigrationService(session)
            report = await migration.preflight()
            assert report.alembic_revision == "20260715_0005"
            assert set(report.admin_ids) == {str(target_admin), str(other_admin)}
            assert {item.owner_user_id for item in report.owner_counts} == {
                str(other_admin),
                str(reader),
            }
            assert report.requires_target_admin is True
            assert report.requires_admin_mapping is True
            with pytest.raises(ApplicationError) as missing_target:
                await migration.convert(target_admin_id=None, map_admin_to_reader_ids=set())
            assert missing_target.value.code == "target_admin_required"
            with pytest.raises(ApplicationError) as missing_mapping:
                await migration.convert(
                    target_admin_id=target_admin,
                    map_admin_to_reader_ids=set(),
                )
            assert missing_mapping.value.code == "admin_mapping_required"
            converted = await migration.convert(
                target_admin_id=target_admin,
                map_admin_to_reader_ids={other_admin},
            )
            assert converted == target_admin

        async with engine.connect() as connection:
            preserved = (
                (
                    await connection.execute(
                        text(
                            "SELECT b.id AS book_id, b.owner_user_id, s.id AS series_id, "
                            "s.owner_user_id AS series_owner, sf.owner_user_id AS file_owner, "
                            "e2.source_edition_id, e3.supersedes_edition_id, "
                            "p.preferred_edition_id, p.last_opened_edition_id, "
                            "rp.overall_progress, rp.version, rs.font_size, rs.theme "
                            "FROM books b JOIN book_series s ON s.id=:series "
                            "JOIN stored_files sf ON sf.id="
                            "'70000000-0000-0000-0000-000000000001' "
                            "JOIN book_editions e2 ON e2.id=:translation "
                            "JOIN book_editions e3 ON e3.id=:successor "
                            "JOIN user_book_preferences p ON p.book_id=b.id AND p.user_id=:reader "
                            "JOIN reading_progresses rp ON rp.user_id=:reader "
                            "JOIN reader_settings rs ON rs.user_id=:reader "
                            "WHERE b.id=:book"
                        ),
                        {
                            "series": series,
                            "translation": translation,
                            "successor": successor,
                            "reader": reader,
                            "book": book,
                        },
                    )
                )
                .mappings()
                .one()
            )
            identities = (
                (
                    await connection.execute(
                        text(
                            "SELECT id, role, password_hash FROM users "
                            "WHERE id IN (:target, :other, :reader) ORDER BY id"
                        ),
                        {"target": target_admin, "other": other_admin, "reader": reader},
                    )
                )
                .mappings()
                .all()
            )
            auth_state = (
                (
                    await connection.execute(
                        text(
                            "SELECT s.revoked_at AS session_revoked, s.revoke_reason, "
                            "r.revoked_at AS refresh_revoked, d.revoked_at AS device_revoked, "
                            "ss.library_owner_user_id, ss.migration_completed_at, "
                            "(SELECT count(*) FROM reader_access_credentials) AS credentials "
                            "FROM auth_sessions s JOIN refresh_tokens r ON r.session_id=s.id "
                            "JOIN devices d ON d.id=s.device_id CROSS JOIN site_settings ss "
                            "WHERE s.id=:session"
                        ),
                        {"session": auth_session},
                    )
                )
                .mappings()
                .one()
            )
        await engine.dispose()

        assert preserved["book_id"] == book
        assert preserved["owner_user_id"] == target_admin
        assert preserved["series_id"] == series
        assert preserved["series_owner"] == target_admin
        assert preserved["file_owner"] == target_admin
        assert preserved["source_edition_id"] == source
        assert preserved["supersedes_edition_id"] == translation
        assert preserved["preferred_edition_id"] == source
        assert preserved["last_opened_edition_id"] == translation
        assert preserved["overall_progress"] == pytest.approx(0.42)
        assert preserved["version"] == 7
        assert preserved["font_size"] == 21
        assert preserved["theme"] == "sepia"
        roles = {row["id"]: row["role"] for row in identities}
        assert roles == {target_admin: "admin", other_admin: "member", reader: "member"}
        assert all(row["password_hash"] is None for row in identities)
        assert auth_state["session_revoked"] is not None
        assert auth_state["revoke_reason"] == "v050_auth_migration"
        assert auth_state["refresh_revoked"] is not None
        assert auth_state["device_revoked"] is not None
        assert auth_state["library_owner_user_id"] == target_admin
        assert auth_state["migration_completed_at"] is not None
        assert auth_state["credentials"] == 0
    finally:
        await drop_migration_database(database_name, admin_url)
