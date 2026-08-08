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
                    "reader_credential_capabilities",
                    "admin_recovery_credentials",
                    "admin_passkeys",
                    "webauthn_challenges",
                    "edition_translation_runs",
                    "provider_credential_versions",
                    "provider_usage_records",
                )
            }
            credential_columns = set(
                (
                    await connection.scalars(
                        text(
                            "SELECT column_name FROM information_schema.columns "
                            "WHERE table_schema='public' "
                            "AND table_name='provider_credential_versions'"
                        )
                    )
                ).all()
            )
            thinking_column = (
                (
                    await connection.execute(
                        text(
                            "SELECT is_nullable, column_default "
                            "FROM information_schema.columns "
                            "WHERE table_schema='public' "
                            "AND table_name='provider_credential_versions' "
                            "AND column_name='thinking_enabled'"
                        )
                    )
                )
                .mappings()
                .one()
            )
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
        assert revision == "20260727_0009"
        assert all(value is not None for value in tables.values())
        assert {
            "provider_name",
            "base_url",
            "model",
            "thinking_enabled",
        } <= credential_columns
        assert thinking_column["is_nullable"] == "NO"
        assert thinking_column["column_default"] == "false"
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
                    "(id, owner_user_id, created_by_user_id, storage_key, "
                    "original_filename, media_type, "
                    "file_format, purpose, size_bytes, sha256) VALUES "
                    "('70000000-0000-0000-0000-000000000050', :owner, :owner, :key, "
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
    empty_book = UUID("50000000-0000-0000-0000-000000000002")
    source = UUID("60000000-0000-0000-0000-000000000001")
    translation = UUID("60000000-0000-0000-0000-000000000002")
    successor = UUID("60000000-0000-0000-0000-000000000003")
    empty_edition = UUID("60000000-0000-0000-0000-000000000004")
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
                    "VALUES (:book, :other, 'Preserved Book', '{}'::jsonb), "
                    "(:empty_book, :other, 'Placeholder Book', '{}'::jsonb)"
                ),
                {"book": book, "empty_book": empty_book, "other": other_admin},
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
                    "'mixed', 'edited', 'draft', '{}'::jsonb), "
                    "(:empty_edition, :empty_book, 'Placeholder', 'en', 'source', NULL, "
                    "'uploaded', 'draft', '{}'::jsonb)"
                ),
                {
                    "source": source,
                    "translation": translation,
                    "successor": successor,
                    "empty_edition": empty_edition,
                    "empty_book": empty_book,
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
                    "VALUES (:series, :book, 1), (:series, :empty_book, 2)"
                ),
                {"series": series, "book": book, "empty_book": empty_book},
            )
            await connection.execute(
                text(
                    "INSERT INTO user_book_preferences "
                    "(user_id, book_id, preferred_edition_id, last_opened_edition_id) "
                    "VALUES (:reader, :book, :source, :translation), "
                    "(:reader, :empty_book, :empty_edition, :empty_edition)"
                ),
                {
                    "reader": reader,
                    "book": book,
                    "source": source,
                    "translation": translation,
                    "empty_book": empty_book,
                    "empty_edition": empty_edition,
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
                    "(:reader, :source, 'reading', 's00001', 0.42, 1, 7, :device), "
                    "(:reader, :empty_edition, 'reading', 's00001', 0.10, 1, 1, :device)"
                ),
                {
                    "reader": reader,
                    "source": source,
                    "empty_edition": empty_edition,
                    "device": device,
                },
            )
        await engine.dispose()

        run_alembic(database_url, "upgrade", "20260715_0005")
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
                            "AND rp.edition_id=:source "
                            "JOIN reader_settings rs ON rs.user_id=:reader "
                            "WHERE b.id=:book"
                        ),
                        {
                            "series": series,
                            "translation": translation,
                            "successor": successor,
                            "source": source,
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

        run_alembic(database_url, "upgrade", "head")
        engine = create_async_engine(database_url)
        async with engine.connect() as connection:
            v090 = (
                (
                    await connection.execute(
                        text(
                            "SELECT (SELECT version_num FROM alembic_version) AS revision, "
                            "b.created_by_user_id AS book_creator, "
                            "e.created_by_user_id AS edition_creator, "
                            "sf.created_by_user_id AS file_creator, "
                            "p.preferred_edition_id, p.last_opened_edition_id, "
                            "(SELECT count(*) FROM book_editions "
                            "WHERE id IN (:translation, :successor)) AS placeholders, "
                            "(SELECT count(*) FROM books WHERE id=:empty_book) AS empty_books, "
                            "(SELECT count(*) FROM book_editions WHERE id=:empty_edition) "
                            "AS empty_editions, "
                            "(SELECT count(*) FROM reading_progresses "
                            "WHERE edition_id=:empty_edition) AS placeholder_progresses, "
                            "(SELECT count(*) FROM user_book_preferences "
                            "WHERE book_id=:empty_book) AS placeholder_preferences, "
                            "to_regclass('public.reader_credential_capabilities') "
                            "AS capability_table, "
                            "to_regclass('public.edition_translation_runs') AS run_table "
                            "FROM books b "
                            "JOIN book_editions e ON e.id=:source "
                            "JOIN stored_files sf ON sf.id="
                            "'70000000-0000-0000-0000-000000000001' "
                            "JOIN user_book_preferences p ON p.book_id=b.id AND p.user_id=:reader "
                            "WHERE b.id=:book"
                        ),
                        {
                            "book": book,
                            "source": source,
                            "reader": reader,
                            "translation": translation,
                            "successor": successor,
                            "empty_book": empty_book,
                            "empty_edition": empty_edition,
                        },
                    )
                )
                .mappings()
                .one()
            )
        await engine.dispose()
        assert v090["revision"] == "20260727_0009"
        assert v090["book_creator"] == target_admin
        assert v090["edition_creator"] == target_admin
        assert v090["file_creator"] == target_admin
        assert v090["preferred_edition_id"] == source
        assert v090["last_opened_edition_id"] is None
        assert v090["placeholders"] == 0
        assert v090["empty_books"] == 0
        assert v090["empty_editions"] == 0
        assert v090["placeholder_progresses"] == 0
        assert v090["placeholder_preferences"] == 0
        assert v090["capability_table"] == "reader_credential_capabilities"
        assert v090["run_table"] == "edition_translation_runs"
    finally:
        await drop_migration_database(database_name, admin_url)


@pytest.mark.integration
async def test_v090_migration_blocks_active_import_and_backfills_read_capability() -> None:
    base_url = os.getenv("TEST_DATABASE_URL")
    if not base_url:
        pytest.skip("TEST_DATABASE_URL is not configured")
    database_name, admin_url, database_url = await create_migration_database(base_url)
    reader_id = UUID("10000000-0000-0000-0000-000000000090")
    credential_id = UUID("20000000-0000-0000-0000-000000000090")
    import_id = UUID("30000000-0000-0000-0000-000000000090")
    try:
        run_alembic(database_url, "upgrade", "20260715_0005")
        engine = create_async_engine(database_url)
        settings = Settings(database_url=database_url)
        factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        async with factory() as session:
            await AdminService(session, settings).initialize("迁移管理员")
            admin_id = await session.scalar(
                text("SELECT library_owner_user_id FROM site_settings WHERE id=1")
            )
            assert admin_id is not None
            await session.execute(
                text(
                    "INSERT INTO users "
                    "(id, username, normalized_username, display_name, role, status) "
                    "VALUES (:reader, 'migration-reader', 'migration-reader', "
                    "'Migration Reader', 'member', 'active')"
                ),
                {"reader": reader_id},
            )
            await session.execute(
                text(
                    "INSERT INTO reader_access_credentials "
                    "(id, user_id, token_hash, credential_hint, status, expires_at, "
                    "allow_new_devices, max_devices, created_by_admin_id, updated_by_admin_id) "
                    "VALUES (:credential, :reader, :token_hash, 'npa_...0090', 'active', "
                    "now() + interval '30 days', true, 3, :admin, :admin)"
                ),
                {
                    "credential": credential_id,
                    "reader": reader_id,
                    "token_hash": "9" * 64,
                    "admin": admin_id,
                },
            )
            await session.execute(
                text(
                    "INSERT INTO library_imports "
                    "(id, owner_user_id, status, operation, original_filename, "
                    "metadata_preview, warnings) "
                    "VALUES (:import_id, :admin, 'ready', 'create_book', 'pending.txt', "
                    "'{}'::jsonb, '[]'::jsonb)"
                ),
                {"import_id": import_id, "admin": admin_id},
            )
            await session.commit()
        await engine.dispose()

        with pytest.raises(subprocess.CalledProcessError):
            run_alembic(database_url, "upgrade", "head")

        engine = create_async_engine(database_url)
        async with engine.begin() as connection:
            revision = await connection.scalar(text("SELECT version_num FROM alembic_version"))
            assert revision == "20260715_0005"
            await connection.execute(
                text("UPDATE library_imports SET status='failed' WHERE id=:import_id"),
                {"import_id": import_id},
            )
        await engine.dispose()

        run_alembic(database_url, "upgrade", "head")
        engine = create_async_engine(database_url)
        async with engine.connect() as connection:
            migrated = (
                (
                    await connection.execute(
                        text(
                            "SELECT av.version_num, ric.capability, li.requested_by_user_id "
                            "FROM alembic_version av "
                            "JOIN reader_credential_capabilities ric "
                            "ON ric.credential_id=:credential "
                            "JOIN library_imports li ON li.id=:import_id"
                        ),
                        {"credential": credential_id, "import_id": import_id},
                    )
                )
                .mappings()
                .one()
            )
        await engine.dispose()
        assert migrated["version_num"] == "20260727_0009"
        assert migrated["capability"] == "library.read"
        assert migrated["requested_by_user_id"] == admin_id
    finally:
        await drop_migration_database(database_name, admin_url)


@pytest.mark.integration
async def test_epub_translation_migration_preserves_txt_and_guards_downgrade() -> None:
    base_url = os.getenv("TEST_DATABASE_URL")
    if not base_url:
        pytest.skip("TEST_DATABASE_URL is not configured")
    database_name, admin_url, database_url = await create_migration_database(base_url)
    credential_id = UUID("87000000-0000-0000-0000-000000000009")
    stored_file_id = UUID("81000000-0000-0000-0000-000000000009")
    book_id = UUID("82000000-0000-0000-0000-000000000009")
    edition_id = UUID("83000000-0000-0000-0000-000000000009")
    edition_file_id = UUID("84000000-0000-0000-0000-000000000009")
    run_id = UUID("85000000-0000-0000-0000-000000000009")
    try:
        run_alembic(database_url, "upgrade", "20260726_0008")
        engine = create_async_engine(database_url)
        settings = Settings(database_url=database_url)
        factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        async with factory() as session:
            await AdminService(session, settings).initialize("EPUB 迁移管理员")
            owner_id = await session.scalar(
                text("SELECT library_owner_user_id FROM site_settings WHERE id=1")
            )
            assert owner_id is not None
            await session.execute(
                text(
                    "INSERT INTO provider_credential_versions "
                    "(id, user_id, provider, base_url, model, version, nonce, ciphertext) "
                    "VALUES (:id, :owner, 'openai_compatible', "
                    "'https://api.openai.com/v1', 'migration-model', 1, "
                    ":nonce, :ciphertext)"
                ),
                {
                    "id": credential_id,
                    "owner": owner_id,
                    "nonce": bytes(12),
                    "ciphertext": b"x" * 17,
                },
            )
            await session.execute(
                text(
                    "INSERT INTO stored_files "
                    "(id, owner_user_id, created_by_user_id, storage_key, "
                    "original_filename, media_type, file_format, purpose, size_bytes, sha256) "
                    "VALUES (:id, :owner, :owner, :storage_key, 'source.txt', "
                    "'text/plain', 'txt', 'edition_source', 3, :sha256)"
                ),
                {
                    "id": stored_file_id,
                    "owner": owner_id,
                    "storage_key": "1" * 64,
                    "sha256": "2" * 64,
                },
            )
            await session.execute(
                text(
                    "INSERT INTO books "
                    "(id, owner_user_id, created_by_user_id, canonical_title, metadata) "
                    "VALUES (:id, :owner, :owner, 'EPUB Migration Book', '{}'::jsonb)"
                ),
                {"id": book_id, "owner": owner_id},
            )
            await session.execute(
                text(
                    "INSERT INTO book_editions "
                    "(id, book_id, created_by_user_id, title, language, content_role, "
                    "creation_method, status, revision, metadata) "
                    "VALUES (:id, :book, :owner, 'Source', 'zh-CN', 'source', "
                    "'uploaded', 'ready', 1, '{}'::jsonb)"
                ),
                {"id": edition_id, "book": book_id, "owner": owner_id},
            )
            await session.execute(
                text(
                    "INSERT INTO edition_files "
                    "(id, edition_id, stored_file_id, revision, is_current, metadata) "
                    "VALUES (:id, :edition, :stored, 1, true, '{}'::jsonb)"
                ),
                {
                    "id": edition_file_id,
                    "edition": edition_id,
                    "stored": stored_file_id,
                },
            )
            await session.execute(
                text(
                    "INSERT INTO edition_translation_runs "
                    "(id, library_owner_user_id, created_by_user_id, "
                    "provider_credential_version_id, book_id, source_edition_id, "
                    "source_edition_file_id, source_revision, source_sha256, source_format, "
                    "target_language, edition_title, configuration_fingerprint, "
                    "configuration_snapshot, client_request_id) "
                    "VALUES (:id, :owner, :owner, :credential, :book, :edition, "
                    ":edition_file, 1, :sha256, 'txt', 'en', 'Migration Translation', "
                    ":fingerprint, '{}'::jsonb, :client_request)"
                ),
                {
                    "id": run_id,
                    "owner": owner_id,
                    "credential": credential_id,
                    "book": book_id,
                    "edition": edition_id,
                    "edition_file": edition_file_id,
                    "sha256": "2" * 64,
                    "fingerprint": "3" * 64,
                    "client_request": UUID("86000000-0000-0000-0000-000000000009"),
                },
            )
            await session.commit()
        await engine.dispose()

        run_alembic(database_url, "upgrade", "head")
        engine = create_async_engine(database_url)
        async with engine.begin() as connection:
            migrated = (
                (
                    await connection.execute(
                        text(
                            "SELECT av.version_num, run.source_format, "
                            "pg_get_constraintdef(c.oid) AS constraint_definition "
                            "FROM alembic_version av "
                            "JOIN edition_translation_runs run ON run.id=:run "
                            "JOIN pg_constraint c "
                            "ON c.conrelid='edition_translation_runs'::regclass "
                            "AND c.conname="
                            "'ck_edition_translation_runs_source_format_supported'"
                        ),
                        {"run": run_id},
                    )
                )
                .mappings()
                .one()
            )
            await connection.execute(
                text("UPDATE edition_translation_runs SET source_format='epub' WHERE id=:run"),
                {"run": run_id},
            )
        assert migrated["version_num"] == "20260727_0009"
        assert migrated["source_format"] == "txt"
        assert "'epub'::file_format" in migrated["constraint_definition"]
        assert "'txt'::file_format" in migrated["constraint_definition"]

        with pytest.raises(subprocess.CalledProcessError) as downgrade_failure:
            run_alembic(database_url, "downgrade", "20260726_0008")
        assert "epub_translation_runs_cannot_downgrade" in (
            (downgrade_failure.value.stdout or "") + (downgrade_failure.value.stderr or "")
        )

        async with engine.begin() as connection:
            state = (
                (
                    await connection.execute(
                        text(
                            "SELECT (SELECT version_num FROM alembic_version) AS revision, "
                            "source_format FROM edition_translation_runs WHERE id=:run"
                        ),
                        {"run": run_id},
                    )
                )
                .mappings()
                .one()
            )
            assert state["revision"] == "20260727_0009"
            assert state["source_format"] == "epub"
            await connection.execute(
                text("UPDATE edition_translation_runs SET source_format='txt' WHERE id=:run"),
                {"run": run_id},
            )
        await engine.dispose()

        run_alembic(database_url, "downgrade", "20260726_0008")
        engine = create_async_engine(database_url)
        async with engine.connect() as connection:
            downgraded = (
                (
                    await connection.execute(
                        text(
                            "SELECT av.version_num, pg_get_constraintdef(c.oid) "
                            "AS constraint_definition "
                            "FROM alembic_version av "
                            "JOIN pg_constraint c "
                            "ON c.conrelid='edition_translation_runs'::regclass "
                            "AND c.conname="
                            "'ck_edition_translation_runs_ck_translation_runs_source_format'"
                        )
                    )
                )
                .mappings()
                .one()
            )
        await engine.dispose()
        assert downgraded["version_num"] == "20260726_0008"
        assert "'txt'::file_format" in downgraded["constraint_definition"]
        assert "'epub'::file_format" not in downgraded["constraint_definition"]
    finally:
        await drop_migration_database(database_name, admin_url)


@pytest.mark.integration
async def test_provider_credential_migration_refuses_and_preserves_unscoped_runs() -> None:
    base_url = os.getenv("TEST_DATABASE_URL")
    if not base_url:
        pytest.skip("TEST_DATABASE_URL is not configured")
    database_name, admin_url, database_url = await create_migration_database(base_url)
    owner_id = UUID("00000000-0000-0000-0000-000000000001")
    stored_file_id = UUID("81000000-0000-0000-0000-000000000001")
    book_id = UUID("82000000-0000-0000-0000-000000000001")
    edition_id = UUID("83000000-0000-0000-0000-000000000001")
    edition_file_id = UUID("84000000-0000-0000-0000-000000000001")
    run_id = UUID("85000000-0000-0000-0000-000000000001")
    try:
        run_alembic(database_url, "upgrade", "20260723_0006")
        engine = create_async_engine(database_url)
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "UPDATE users SET username='__site_admin__', "
                    "normalized_username='__site_admin__', display_name='管理员', "
                    "status='active' WHERE id=:owner"
                ),
                {"owner": owner_id},
            )
            await connection.execute(
                text(
                    "UPDATE site_settings SET library_owner_user_id=:owner, "
                    "migration_completed_at=now() WHERE id=1"
                ),
                {"owner": owner_id},
            )
            await connection.execute(
                text(
                    "INSERT INTO stored_files "
                    "(id, owner_user_id, created_by_user_id, storage_key, "
                    "original_filename, media_type, file_format, purpose, size_bytes, sha256) "
                    "VALUES (:id, :owner, :owner, :storage_key, 'source.txt', "
                    "'text/plain', 'txt', 'edition_source', 3, :sha256)"
                ),
                {
                    "id": stored_file_id,
                    "owner": owner_id,
                    "storage_key": "1" * 64,
                    "sha256": "2" * 64,
                },
            )
            await connection.execute(
                text(
                    "INSERT INTO books "
                    "(id, owner_user_id, created_by_user_id, canonical_title, metadata) "
                    "VALUES (:id, :owner, :owner, 'Legacy Run Book', '{}'::jsonb)"
                ),
                {"id": book_id, "owner": owner_id},
            )
            await connection.execute(
                text(
                    "INSERT INTO book_editions "
                    "(id, book_id, created_by_user_id, title, language, content_role, "
                    "creation_method, status, revision, metadata) "
                    "VALUES (:id, :book, :owner, 'Source', 'zh-CN', 'source', "
                    "'uploaded', 'ready', 1, '{}'::jsonb)"
                ),
                {"id": edition_id, "book": book_id, "owner": owner_id},
            )
            await connection.execute(
                text(
                    "INSERT INTO edition_files "
                    "(id, edition_id, stored_file_id, revision, is_current, metadata) "
                    "VALUES (:id, :edition, :stored, 1, true, '{}'::jsonb)"
                ),
                {
                    "id": edition_file_id,
                    "edition": edition_id,
                    "stored": stored_file_id,
                },
            )
            await connection.execute(
                text(
                    "INSERT INTO edition_translation_runs "
                    "(id, library_owner_user_id, created_by_user_id, book_id, "
                    "source_edition_id, source_edition_file_id, source_revision, "
                    "source_sha256, source_format, target_language, edition_title, "
                    "configuration_fingerprint, configuration_snapshot, client_request_id) "
                    "VALUES (:id, :owner, :owner, :book, :edition, :edition_file, 1, "
                    ":sha256, 'txt', 'en', 'Legacy Translation', :fingerprint, "
                    "'{}'::jsonb, :client_request)"
                ),
                {
                    "id": run_id,
                    "owner": owner_id,
                    "book": book_id,
                    "edition": edition_id,
                    "edition_file": edition_file_id,
                    "sha256": "2" * 64,
                    "fingerprint": "3" * 64,
                    "client_request": UUID("86000000-0000-0000-0000-000000000001"),
                },
            )
        await engine.dispose()

        with pytest.raises(subprocess.CalledProcessError):
            run_alembic(database_url, "upgrade", "head")

        engine = create_async_engine(database_url)
        async with engine.connect() as connection:
            state = (
                (
                    await connection.execute(
                        text(
                            "SELECT (SELECT version_num FROM alembic_version) AS revision, "
                            "(SELECT count(*) FROM edition_translation_runs WHERE id=:run) "
                            "AS run_count, "
                            "to_regclass('public.provider_credential_versions') "
                            "AS credential_table"
                        ),
                        {"run": run_id},
                    )
                )
                .mappings()
                .one()
            )
        await engine.dispose()
        assert state["revision"] == "20260723_0006"
        assert state["run_count"] == 1
        assert state["credential_table"] is None
    finally:
        await drop_migration_database(database_name, admin_url)


@pytest.mark.integration
async def test_multi_provider_migration_preserves_legacy_credential_semantics() -> None:
    base_url = os.getenv("TEST_DATABASE_URL")
    if not base_url:
        pytest.skip("TEST_DATABASE_URL is not configured")
    database_name, admin_url, database_url = await create_migration_database(base_url)
    owner_id = UUID("00000000-0000-0000-0000-000000000001")
    credential_id = UUID("87000000-0000-0000-0000-000000000001")
    try:
        run_alembic(database_url, "upgrade", "20260726_0007")
        engine = create_async_engine(database_url)
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "INSERT INTO provider_credential_versions "
                    "(id, user_id, provider, version, algorithm, nonce, ciphertext) "
                    "VALUES (:id, :user, 'openai_compatible', 1, "
                    "'aes-256-gcm-v1', :nonce, :ciphertext)"
                ),
                {
                    "id": credential_id,
                    "user": owner_id,
                    "nonce": bytes(12),
                    "ciphertext": b"x" * 17,
                },
            )
        await engine.dispose()

        run_alembic(database_url, "upgrade", "head")
        engine = create_async_engine(database_url)
        async with engine.connect() as connection:
            migrated = (
                (
                    await connection.execute(
                        text(
                            "SELECT provider, provider_name, base_url, model, "
                            "thinking_enabled, algorithm "
                            "FROM provider_credential_versions WHERE id=:id"
                        ),
                        {"id": credential_id},
                    )
                )
                .mappings()
                .one()
            )
            algorithm_default = await connection.scalar(
                text(
                    "SELECT column_default FROM information_schema.columns "
                    "WHERE table_schema='public' "
                    "AND table_name='provider_credential_versions' "
                    "AND column_name='algorithm'"
                )
            )
            routing_defaults = dict(
                (
                    await connection.execute(
                        text(
                            "SELECT column_name, column_default "
                            "FROM information_schema.columns "
                            "WHERE table_schema='public' "
                            "AND table_name='provider_credential_versions' "
                            "AND column_name IN ('base_url', 'model')"
                        )
                    )
                ).all()
            )
            version_constraint = await connection.scalar(
                text(
                    "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                    "WHERE conrelid='provider_credential_versions'::regclass "
                    "AND conname='uq_provider_credential_versions_user_version'"
                )
            )
            check_constraints = set(
                (
                    await connection.execute(
                        text(
                            "SELECT conname FROM pg_constraint "
                            "WHERE conrelid='provider_credential_versions'::regclass "
                            "AND contype='c'"
                        )
                    )
                )
                .scalars()
                .all()
            )
            current_index = await connection.scalar(
                text(
                    "SELECT indexdef FROM pg_indexes "
                    "WHERE schemaname='public' "
                    "AND tablename='provider_credential_versions' "
                    "AND indexname='uq_provider_credential_versions_current'"
                )
            )
            revision = await connection.scalar(text("SELECT version_num FROM alembic_version"))
        await engine.dispose()

        assert revision == "20260727_0009"
        assert dict(migrated) == {
            "provider": "openai_compatible",
            "provider_name": None,
            "base_url": "https://api.openai.com/v1",
            "model": "gpt-4.1-mini",
            "thinking_enabled": False,
            "algorithm": "aes-256-gcm-v1",
        }
        assert algorithm_default is not None
        assert "aes-256-gcm-v2" in algorithm_default
        assert routing_defaults == {"base_url": None, "model": None}
        assert version_constraint == "UNIQUE (user_id, version)"
        assert {
            "ck_provider_credential_versions_provider_known",
            "ck_provider_credential_versions_provider_name_matches_provider",
            "ck_provider_credential_versions_base_url_not_blank",
            "ck_provider_credential_versions_model_not_blank",
            "ck_provider_credential_versions_algorithm_supported",
        } <= check_constraints
        assert current_index is not None
        assert "UNIQUE INDEX" in current_index
        assert "USING btree (user_id)" in current_index
        assert "retired_at IS NULL" in current_index
        assert "revoked_at IS NULL" in current_index
    finally:
        await drop_migration_database(database_name, admin_url)


@pytest.mark.integration
async def test_multi_provider_migration_downgrade_refuses_incompatible_rows() -> None:
    base_url = os.getenv("TEST_DATABASE_URL")
    if not base_url:
        pytest.skip("TEST_DATABASE_URL is not configured")
    database_name, admin_url, database_url = await create_migration_database(base_url)
    owner_id = UUID("00000000-0000-0000-0000-000000000001")
    credential_id = UUID("87000000-0000-0000-0000-000000000002")
    try:
        run_alembic(database_url, "upgrade", "head")
        engine = create_async_engine(database_url)

        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "INSERT INTO provider_credential_versions "
                    "(id, user_id, provider, base_url, model, version, nonce, ciphertext) "
                    "VALUES (:id, :user, 'openai_compatible', "
                    "'https://api.openai.com/v1', 'explicit-test-model', "
                    "1, :nonce, :ciphertext)"
                ),
                {
                    "id": credential_id,
                    "user": owner_id,
                    "nonce": bytes(12),
                    "ciphertext": b"x" * 17,
                },
            )
            algorithm = await connection.scalar(
                text("SELECT algorithm FROM provider_credential_versions WHERE id=:id"),
                {"id": credential_id},
            )
        assert algorithm == "aes-256-gcm-v2"

        with pytest.raises(subprocess.CalledProcessError) as v2_failure:
            run_alembic(database_url, "downgrade", "20260726_0007")
        assert "v0100_multi_provider_credentials_cannot_downgrade" in (
            (v2_failure.value.stdout or "") + (v2_failure.value.stderr or "")
        )

        async with engine.begin() as connection:
            await connection.execute(
                text("DELETE FROM provider_credential_versions WHERE id=:id"),
                {"id": credential_id},
            )
            await connection.execute(
                text(
                    "INSERT INTO provider_credential_versions "
                    "(id, user_id, provider, base_url, model, version, algorithm, "
                    "nonce, ciphertext) "
                    "VALUES (:id, :user, 'deepseek', 'https://api.deepseek.com/v1', "
                    "'deepseek-chat', 1, 'aes-256-gcm-v1', :nonce, :ciphertext)"
                ),
                {
                    "id": credential_id,
                    "user": owner_id,
                    "nonce": bytes(12),
                    "ciphertext": b"x" * 17,
                },
            )

        with pytest.raises(subprocess.CalledProcessError) as provider_failure:
            run_alembic(database_url, "downgrade", "20260726_0007")
        assert "v0100_multi_provider_credentials_cannot_downgrade" in (
            (provider_failure.value.stdout or "") + (provider_failure.value.stderr or "")
        )

        async with engine.connect() as connection:
            revision = await connection.scalar(text("SELECT version_num FROM alembic_version"))
        await engine.dispose()
        assert revision == "20260727_0009"
    finally:
        await drop_migration_database(database_name, admin_url)
