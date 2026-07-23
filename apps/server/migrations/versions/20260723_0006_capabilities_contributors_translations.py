"""Add v0.9 credential capabilities, contributors, and translation runs.

Revision ID: 20260723_0006
Revises: 20260715_0005
Create Date: 2026-07-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260723_0006"
down_revision: str | None = "20260715_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

file_format = postgresql.ENUM(
    "epub",
    "txt",
    "jpeg",
    "png",
    "webp",
    "gif",
    name="file_format",
    create_type=False,
)


def _preflight_and_remove_placeholders() -> None:
    op.execute(
        """
        DO $$
        DECLARE
            site_count integer;
            owner_id uuid;
            converted_at timestamptz;
            pristine boolean;
            placeholder_editions integer;
            placeholder_books integer;
            credential_count integer;
        BEGIN
            SELECT count(*) INTO site_count FROM site_settings;
            IF site_count <> 1 THEN
                RAISE EXCEPTION 'v090_preflight_site_settings';
            END IF;

            SELECT library_owner_user_id, migration_completed_at
            INTO owner_id, converted_at
            FROM site_settings WHERE id = 1;

            pristine := owner_id IS NULL
                AND converted_at IS NULL
                AND NOT EXISTS (
                    SELECT 1 FROM users
                    WHERE id <> '00000000-0000-0000-0000-000000000001'::uuid
                        OR role <> 'admin'
                        OR status <> 'pending_setup'
                )
                AND NOT EXISTS (SELECT 1 FROM books)
                AND NOT EXISTS (SELECT 1 FROM book_editions)
                AND NOT EXISTS (SELECT 1 FROM stored_files)
                AND NOT EXISTS (SELECT 1 FROM library_imports)
                AND NOT EXISTS (SELECT 1 FROM reader_access_credentials);

            IF NOT pristine THEN
                IF owner_id IS NULL OR converted_at IS NULL THEN
                    RAISE EXCEPTION 'v090_preflight_v050_conversion_required';
                END IF;
                IF (SELECT count(*) FROM users WHERE role = 'admin') <> 1
                    OR NOT EXISTS (
                        SELECT 1 FROM users WHERE id = owner_id AND role = 'admin'
                    ) THEN
                    RAISE EXCEPTION 'v090_preflight_unique_admin_required';
                END IF;
                IF EXISTS (SELECT 1 FROM books WHERE owner_user_id <> owner_id)
                    OR EXISTS (SELECT 1 FROM stored_files WHERE owner_user_id <> owner_id)
                    OR EXISTS (SELECT 1 FROM library_imports WHERE owner_user_id <> owner_id)
                    OR EXISTS (SELECT 1 FROM book_series WHERE owner_user_id <> owner_id) THEN
                    RAISE EXCEPTION 'v090_preflight_owner_mismatch';
                END IF;
                IF EXISTS (
                    SELECT 1 FROM library_imports
                    WHERE status IN ('pending', 'processing', 'ready')
                ) THEN
                    RAISE EXCEPTION 'v090_preflight_active_imports';
                END IF;
                IF EXISTS (
                    SELECT 1
                    FROM edition_files ef
                    LEFT JOIN stored_files sf ON sf.id = ef.stored_file_id
                    LEFT JOIN stored_files nf ON nf.id = ef.normalized_stored_file_id
                    WHERE sf.id IS NULL
                        OR sf.owner_user_id <> owner_id
                        OR (ef.normalized_stored_file_id IS NOT NULL AND nf.id IS NULL)
                        OR (nf.id IS NOT NULL AND nf.owner_user_id <> owner_id)
                ) THEN
                    RAISE EXCEPTION 'v090_preflight_file_reference_mismatch';
                END IF;
                IF EXISTS (
                    SELECT ef.edition_id
                    FROM edition_files ef
                    GROUP BY ef.edition_id
                    HAVING count(*) FILTER (WHERE ef.is_current) <> 1
                ) THEN
                    RAISE EXCEPTION 'v090_preflight_current_file_mismatch';
                END IF;
            END IF;

            SELECT count(*) INTO placeholder_editions
            FROM book_editions be
            WHERE NOT EXISTS (
                SELECT 1 FROM edition_files ef WHERE ef.edition_id = be.id
            );
            SELECT count(*) INTO placeholder_books
            FROM books b
            WHERE NOT EXISTS (
                SELECT 1 FROM book_editions be
                JOIN edition_files ef ON ef.edition_id = be.id
                WHERE be.book_id = b.id
            );
            SELECT count(*) INTO credential_count FROM reader_access_credentials;
            RAISE NOTICE 'v0.9 migration counts: editions=%, books=%, credentials=%',
                placeholder_editions, placeholder_books, credential_count;
        END $$;
        """
    )

    no_file_editions = """
        SELECT be.id FROM book_editions be
        WHERE NOT EXISTS (
            SELECT 1 FROM edition_files ef WHERE ef.edition_id = be.id
        )
    """
    op.execute(
        f"UPDATE user_book_preferences SET preferred_edition_id = NULL "
        f"WHERE preferred_edition_id IN ({no_file_editions})"
    )
    op.execute(
        f"UPDATE user_book_preferences SET last_opened_edition_id = NULL "
        f"WHERE last_opened_edition_id IN ({no_file_editions})"
    )
    op.execute(f"DELETE FROM reading_progresses WHERE edition_id IN ({no_file_editions})")
    op.execute(
        f"UPDATE book_editions SET source_edition_id = NULL "
        f"WHERE source_edition_id IN ({no_file_editions})"
    )
    op.execute(
        f"UPDATE book_editions SET supersedes_edition_id = NULL "
        f"WHERE supersedes_edition_id IN ({no_file_editions})"
    )
    op.execute(f"DELETE FROM book_editions WHERE id IN ({no_file_editions})")

    empty_books = (
        "SELECT b.id FROM books b "
        "WHERE NOT EXISTS (SELECT 1 FROM book_editions be WHERE be.book_id = b.id)"
    )
    op.execute(f"DELETE FROM series_memberships WHERE book_id IN ({empty_books})")
    op.execute(f"DELETE FROM user_book_preferences WHERE book_id IN ({empty_books})")
    op.execute(f"DELETE FROM books WHERE id IN ({empty_books})")


def _add_contributor_columns() -> None:
    uuid_type = postgresql.UUID(as_uuid=True)
    for table_name, column_name in (
        ("books", "created_by_user_id"),
        ("book_editions", "created_by_user_id"),
        ("stored_files", "created_by_user_id"),
        ("library_imports", "requested_by_user_id"),
    ):
        op.add_column(table_name, sa.Column(column_name, uuid_type, nullable=True))

    op.execute(
        "UPDATE books SET created_by_user_id = "
        "(SELECT library_owner_user_id FROM site_settings WHERE id = 1)"
    )
    op.execute(
        "UPDATE book_editions SET created_by_user_id = "
        "(SELECT library_owner_user_id FROM site_settings WHERE id = 1)"
    )
    op.execute(
        "UPDATE stored_files SET created_by_user_id = "
        "(SELECT library_owner_user_id FROM site_settings WHERE id = 1)"
    )
    op.execute(
        "UPDATE library_imports SET requested_by_user_id = "
        "(SELECT library_owner_user_id FROM site_settings WHERE id = 1)"
    )

    for table_name, column_name, constraint_name, index_name in (
        (
            "books",
            "created_by_user_id",
            "fk_books_created_by_user_id_users",
            "ix_books_created_by_user_id",
        ),
        (
            "book_editions",
            "created_by_user_id",
            "fk_book_editions_created_by_user_id_users",
            "ix_book_editions_created_by_user_id",
        ),
        (
            "stored_files",
            "created_by_user_id",
            "fk_stored_files_created_by_user_id_users",
            "ix_stored_files_created_by_user_id",
        ),
        (
            "library_imports",
            "requested_by_user_id",
            "fk_library_imports_requested_by_user_id_users",
            "ix_library_imports_requested_by_user_id",
        ),
    ):
        op.alter_column(table_name, column_name, nullable=False)
        op.create_foreign_key(
            constraint_name,
            table_name,
            "users",
            [column_name],
            ["id"],
            ondelete="RESTRICT",
        )
        op.create_index(index_name, table_name, [column_name])


def _create_capabilities() -> None:
    op.create_table(
        "reader_credential_capabilities",
        sa.Column("credential_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("capability", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "capability IN ('library.read', 'library.upload', 'translation.use')",
            name="ck_reader_credential_capabilities_known_capability",
        ),
        sa.ForeignKeyConstraint(
            ["credential_id"],
            ["reader_access_credentials.id"],
            name="fk_reader_credential_capabilities_credential_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "credential_id",
            "capability",
            name="pk_reader_credential_capabilities",
        ),
    )
    op.create_index(
        "ix_reader_credential_capabilities_capability",
        "reader_credential_capabilities",
        ["capability"],
    )
    op.execute(
        "INSERT INTO reader_credential_capabilities (credential_id, capability) "
        "SELECT id, 'library.read' FROM reader_access_credentials"
    )


def _create_translation_runs() -> None:
    op.create_table(
        "edition_translation_runs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("library_owner_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("book_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_edition_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_edition_file_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_revision", sa.Integer(), nullable=False),
        sa.Column("source_sha256", sa.String(length=64), nullable=False),
        sa.Column("source_format", file_format, nullable=False),
        sa.Column("target_language", sa.String(length=100), nullable=False),
        sa.Column("edition_title", sa.String(), nullable=False),
        sa.Column("supersedes_edition_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("configuration_fingerprint", sa.String(length=64), nullable=False),
        sa.Column(
            "configuration_snapshot",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("client_request_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("remote_project_id", sa.String(length=128), nullable=True),
        sa.Column("remote_job_id", sa.String(length=128), nullable=True),
        sa.Column("remote_artifact_id", sa.String(length=128), nullable=True),
        sa.Column("remote_request_id", sa.String(length=128), nullable=True),
        sa.Column("remote_status", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=32), server_default="preparing", nullable=False),
        sa.Column("progress", sa.Float(), server_default="0", nullable=False),
        sa.Column("generated_edition_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("error_code", sa.String(length=100), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "error_details",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("retry_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "cleanup_status", sa.String(length=32), server_default="not_required", nullable=False
        ),
        sa.Column("cleanup_error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("source_revision >= 1", name="ck_translation_runs_source_revision"),
        sa.CheckConstraint(
            "source_sha256 ~ '^[0-9a-f]{64}$'", name="ck_translation_runs_source_sha256"
        ),
        sa.CheckConstraint("source_format = 'txt'", name="ck_translation_runs_source_format"),
        sa.CheckConstraint(
            "length(btrim(target_language)) > 0",
            name="ck_translation_runs_target_language",
        ),
        sa.CheckConstraint(
            "length(btrim(edition_title)) > 0", name="ck_translation_runs_edition_title"
        ),
        sa.CheckConstraint(
            "configuration_fingerprint ~ '^[0-9a-f]{64}$'",
            name="ck_translation_runs_configuration_fingerprint",
        ),
        sa.CheckConstraint("progress >= 0 AND progress <= 1", name="ck_translation_runs_progress"),
        sa.CheckConstraint("retry_count >= 0", name="ck_translation_runs_retry_count"),
        sa.CheckConstraint(
            "status IN ('preparing', 'queued', 'running', 'paused', 'cancelling', "
            "'cancelled', 'partially_succeeded', 'failed', 'ingesting', 'succeeded', "
            "'attention_required')",
            name="ck_translation_runs_status",
        ),
        sa.CheckConstraint(
            "cleanup_status IN ('not_required', 'pending', 'succeeded', 'failed')",
            name="ck_translation_runs_cleanup_status",
        ),
        sa.ForeignKeyConstraint(
            ["library_owner_user_id"],
            ["users.id"],
            name="fk_translation_runs_library_owner",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            name="fk_translation_runs_created_by",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["book_id"], ["books.id"], name="fk_translation_runs_book", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["source_edition_id"],
            ["book_editions.id"],
            name="fk_translation_runs_source_edition",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["source_edition_file_id"],
            ["edition_files.id"],
            name="fk_translation_runs_source_file",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["supersedes_edition_id"],
            ["book_editions.id"],
            name="fk_translation_runs_supersedes",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["generated_edition_id"],
            ["book_editions.id"],
            name="fk_translation_runs_generated_edition",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_edition_translation_runs"),
        sa.UniqueConstraint(
            "created_by_user_id",
            "client_request_id",
            name="uq_translation_runs_actor_client_request",
        ),
    )
    op.create_index(
        "uq_translation_runs_active_equivalent",
        "edition_translation_runs",
        ["source_edition_file_id", "target_language", "configuration_fingerprint"],
        unique=True,
        postgresql_where=sa.text(
            "status IN ('preparing', 'queued', 'running', 'paused', 'cancelling', "
            "'ingesting', 'attention_required')"
        ),
    )
    for index_name, column_name in (
        ("uq_translation_runs_remote_project", "remote_project_id"),
        ("uq_translation_runs_remote_job", "remote_job_id"),
        ("uq_translation_runs_remote_artifact", "remote_artifact_id"),
        ("uq_translation_runs_generated_edition", "generated_edition_id"),
    ):
        op.create_index(
            index_name,
            "edition_translation_runs",
            [column_name],
            unique=True,
            postgresql_where=sa.text(f"{column_name} IS NOT NULL"),
        )
    op.create_index(
        "ix_translation_runs_owner_created",
        "edition_translation_runs",
        ["library_owner_user_id", "created_at"],
    )
    op.create_index(
        "ix_translation_runs_actor_created",
        "edition_translation_runs",
        ["created_by_user_id", "created_at"],
    )
    op.create_index(
        "ix_translation_runs_book_created",
        "edition_translation_runs",
        ["book_id", "created_at"],
    )
    op.create_index(
        "ix_translation_runs_source_edition",
        "edition_translation_runs",
        ["source_edition_id"],
    )


def upgrade() -> None:
    _preflight_and_remove_placeholders()
    _add_contributor_columns()
    _create_capabilities()
    _create_translation_runs()


def downgrade() -> None:
    raise RuntimeError(
        "v0.9 performs destructive placeholder cleanup; restore the coordinated backup instead"
    )
