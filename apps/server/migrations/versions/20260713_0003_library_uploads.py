"""Add durable library files, revisions, covers, and import records.

Revision ID: 20260713_0003
Revises: 20260711_0002
Create Date: 2026-07-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260713_0003"
down_revision: str | None = "20260711_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

file_format = postgresql.ENUM(
    "epub", "txt", "jpeg", "png", "webp", "gif", name="file_format", create_type=False
)
stored_file_purpose = postgresql.ENUM(
    "edition_source",
    "normalized_text",
    "book_cover",
    "cover_thumbnail",
    name="stored_file_purpose",
    create_type=False,
)
library_import_status = postgresql.ENUM(
    "pending",
    "processing",
    "ready",
    "succeeded",
    "failed",
    name="library_import_status",
    create_type=False,
)
library_import_operation = postgresql.ENUM(
    "create_book",
    "add_edition",
    "replace_edition_file",
    name="library_import_operation",
    create_type=False,
)


def timestamp(name: str, *, nullable: bool = False) -> sa.Column[sa.DateTime]:
    return sa.Column(
        name,
        sa.DateTime(timezone=True),
        server_default=sa.text("now()") if not nullable else None,
        nullable=nullable,
    )


def upgrade() -> None:
    bind = op.get_bind()
    file_format.create(bind, checkfirst=True)
    stored_file_purpose.create(bind, checkfirst=True)
    library_import_status.create(bind, checkfirst=True)
    library_import_operation.create(bind, checkfirst=True)

    op.create_table(
        "stored_files",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("owner_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("storage_key", sa.String(length=64), nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("media_type", sa.String(length=100), nullable=False),
        sa.Column("file_format", file_format, nullable=False),
        sa.Column("purpose", stored_file_purpose, nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        timestamp("created_at"),
        sa.CheckConstraint("size_bytes >= 0", name="ck_stored_files_size_bytes_nonnegative"),
        sa.CheckConstraint(
            "storage_key ~ '^[0-9a-f]{64}$'",
            name="ck_stored_files_storage_key_lower_hex",
        ),
        sa.CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'", name="ck_stored_files_sha256_lower_hex"),
        sa.CheckConstraint(
            "length(btrim(original_filename)) > 0",
            name="ck_stored_files_original_filename_not_blank",
        ),
        sa.CheckConstraint(
            "(purpose = 'edition_source' AND file_format IN ('epub', 'txt')) OR "
            "(purpose = 'normalized_text' AND file_format = 'txt') OR "
            "(purpose = 'book_cover' AND file_format IN ('jpeg', 'png', 'webp', 'gif')) OR "
            "(purpose = 'cover_thumbnail' AND file_format = 'jpeg')",
            name="ck_stored_files_purpose_format_consistent",
        ),
        sa.ForeignKeyConstraint(
            ["owner_user_id"],
            ["users.id"],
            name="fk_stored_files_owner_user_id_users",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_stored_files"),
        sa.UniqueConstraint("storage_key", name="uq_stored_files_storage_key"),
    )
    op.create_index("ix_stored_files_owner_user_id", "stored_files", ["owner_user_id"])
    op.create_index("ix_stored_files_owner_sha256", "stored_files", ["owner_user_id", "sha256"])

    op.add_column("books", sa.Column("cover_file_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column(
        "books",
        sa.Column("cover_thumbnail_file_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_books_cover_file_id_stored_files",
        "books",
        "stored_files",
        ["cover_file_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_books_cover_thumbnail_file_id_stored_files",
        "books",
        "stored_files",
        ["cover_thumbnail_file_id"],
        ["id"],
        ondelete="RESTRICT",
    )

    op.create_table(
        "edition_files",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("edition_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("stored_file_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("normalized_stored_file_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("is_current", sa.Boolean(), nullable=False),
        sa.Column("text_encoding", sa.String(length=40), nullable=True),
        sa.Column("content_item_count", sa.Integer(), nullable=True),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        timestamp("created_at"),
        sa.CheckConstraint("revision >= 1", name="ck_edition_files_revision_at_least_one"),
        sa.CheckConstraint(
            "content_item_count IS NULL OR content_item_count >= 0",
            name="ck_edition_files_content_item_count_nonnegative",
        ),
        sa.CheckConstraint(
            "normalized_stored_file_id IS NULL OR normalized_stored_file_id <> stored_file_id",
            name="ck_edition_files_normalized_file_is_distinct",
        ),
        sa.ForeignKeyConstraint(
            ["edition_id"],
            ["book_editions.id"],
            name="fk_edition_files_edition_id_book_editions",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["normalized_stored_file_id"],
            ["stored_files.id"],
            name="fk_edition_files_normalized_stored_file_id_stored_files",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["stored_file_id"],
            ["stored_files.id"],
            name="fk_edition_files_stored_file_id_stored_files",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_edition_files"),
        sa.UniqueConstraint("edition_id", "revision", name="uq_edition_files_edition_revision"),
    )
    op.create_index("ix_edition_files_edition_id", "edition_files", ["edition_id"])
    op.create_index("ix_edition_files_stored_file_id", "edition_files", ["stored_file_id"])
    op.create_index(
        "ix_edition_files_normalized_stored_file_id",
        "edition_files",
        ["normalized_stored_file_id"],
    )
    op.create_index(
        "uq_edition_files_current",
        "edition_files",
        ["edition_id"],
        unique=True,
        postgresql_where=sa.text("is_current"),
    )

    op.create_table(
        "library_imports",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("owner_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", library_import_status, nullable=False),
        sa.Column("operation", library_import_operation, nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("submitted_media_type", sa.String(length=200), nullable=True),
        sa.Column("file_format", file_format, nullable=True),
        sa.Column("size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("sha256", sa.String(length=64), nullable=True),
        sa.Column("target_book_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("target_edition_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("stored_file_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("temporary_storage_key", sa.String(length=64), nullable=True),
        sa.Column("normalized_temporary_storage_key", sa.String(length=64), nullable=True),
        sa.Column("cover_temporary_storage_key", sa.String(length=64), nullable=True),
        sa.Column("cover_thumbnail_temporary_storage_key", sa.String(length=64), nullable=True),
        sa.Column("cover_filename", sa.String(length=255), nullable=True),
        sa.Column("cover_media_type", sa.String(length=100), nullable=True),
        sa.Column("cover_file_format", file_format, nullable=True),
        sa.Column("text_encoding", sa.String(length=40), nullable=True),
        sa.Column("content_item_count", sa.Integer(), nullable=True),
        sa.Column(
            "metadata_preview",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "warnings",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("error_code", sa.String(length=100), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        timestamp("created_at"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "length(btrim(original_filename)) > 0",
            name="ck_library_imports_original_filename_not_blank",
        ),
        sa.CheckConstraint(
            "size_bytes IS NULL OR size_bytes >= 0",
            name="ck_library_imports_size_bytes_nonnegative",
        ),
        sa.CheckConstraint(
            "sha256 IS NULL OR sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_library_imports_sha256_lower_hex",
        ),
        sa.CheckConstraint(
            "content_item_count IS NULL OR content_item_count >= 0",
            name="ck_library_imports_content_item_count_nonnegative",
        ),
        sa.CheckConstraint(
            "(temporary_storage_key IS NULL OR "
            "temporary_storage_key ~ '^[0-9a-f]{64}$') AND "
            "(normalized_temporary_storage_key IS NULL OR "
            "normalized_temporary_storage_key ~ '^[0-9a-f]{64}$') AND "
            "(cover_temporary_storage_key IS NULL OR "
            "cover_temporary_storage_key ~ '^[0-9a-f]{64}$') AND "
            "(cover_thumbnail_temporary_storage_key IS NULL OR "
            "cover_thumbnail_temporary_storage_key ~ '^[0-9a-f]{64}$')",
            name="ck_library_imports_temporary_keys_lower_hex",
        ),
        sa.ForeignKeyConstraint(
            ["owner_user_id"],
            ["users.id"],
            name="fk_library_imports_owner_user_id_users",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["stored_file_id"],
            ["stored_files.id"],
            name="fk_library_imports_stored_file_id_stored_files",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["target_book_id"],
            ["books.id"],
            name="fk_library_imports_target_book_id_books",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["target_edition_id"],
            ["book_editions.id"],
            name="fk_library_imports_target_edition_id_book_editions",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_library_imports"),
    )
    op.create_index("ix_library_imports_owner_user_id", "library_imports", ["owner_user_id"])
    op.create_index("ix_library_imports_target_book_id", "library_imports", ["target_book_id"])
    op.create_index(
        "ix_library_imports_target_edition_id", "library_imports", ["target_edition_id"]
    )
    op.create_index(
        "ix_library_imports_owner_created",
        "library_imports",
        ["owner_user_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_library_imports_owner_created", table_name="library_imports")
    op.drop_index("ix_library_imports_target_edition_id", table_name="library_imports")
    op.drop_index("ix_library_imports_target_book_id", table_name="library_imports")
    op.drop_index("ix_library_imports_owner_user_id", table_name="library_imports")
    op.drop_table("library_imports")
    op.drop_index("uq_edition_files_current", table_name="edition_files")
    op.drop_index("ix_edition_files_normalized_stored_file_id", table_name="edition_files")
    op.drop_index("ix_edition_files_stored_file_id", table_name="edition_files")
    op.drop_index("ix_edition_files_edition_id", table_name="edition_files")
    op.drop_table("edition_files")
    op.drop_constraint("fk_books_cover_thumbnail_file_id_stored_files", "books", type_="foreignkey")
    op.drop_constraint("fk_books_cover_file_id_stored_files", "books", type_="foreignkey")
    op.drop_column("books", "cover_thumbnail_file_id")
    op.drop_column("books", "cover_file_id")
    op.drop_index("ix_stored_files_owner_sha256", table_name="stored_files")
    op.drop_index("ix_stored_files_owner_user_id", table_name="stored_files")
    op.drop_table("stored_files")

    bind = op.get_bind()
    library_import_operation.drop(bind, checkfirst=True)
    library_import_status.drop(bind, checkfirst=True)
    stored_file_purpose.drop(bind, checkfirst=True)
    file_format.drop(bind, checkfirst=True)
