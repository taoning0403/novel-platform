"""Add reader progress, settings, recent-reading data, and custom series.

Revision ID: 20260714_0004
Revises: 20260713_0003
Create Date: 2026-07-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260714_0004"
down_revision: str | None = "20260713_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

reading_status = postgresql.ENUM(
    "not_started", "reading", "finished", name="reading_status", create_type=False
)
reader_theme = postgresql.ENUM("light", "dark", "sepia", name="reader_theme", create_type=False)
reader_font_family = postgresql.ENUM(
    "serif", "sans", "system", name="reader_font_family", create_type=False
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
    reading_status.create(bind, checkfirst=True)
    reader_theme.create(bind, checkfirst=True)
    reader_font_family.create(bind, checkfirst=True)

    op.create_table(
        "book_series",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("owner_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        timestamp("created_at"),
        timestamp("updated_at"),
        sa.CheckConstraint(
            "length(btrim(name)) > 0",
            name="ck_book_series_name_not_blank",
        ),
        sa.ForeignKeyConstraint(
            ["owner_user_id"],
            ["users.id"],
            name="fk_book_series_owner_user_id_users",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_book_series"),
    )
    op.create_index("ix_book_series_owner_user_id", "book_series", ["owner_user_id"])
    op.create_index(
        "ix_book_series_owner_updated",
        "book_series",
        ["owner_user_id", "updated_at"],
    )

    op.create_table(
        "series_memberships",
        sa.Column("series_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("book_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("position", sa.BigInteger(), nullable=False),
        timestamp("added_at"),
        sa.CheckConstraint(
            "position >= 1",
            name="ck_series_memberships_position_positive",
        ),
        sa.ForeignKeyConstraint(
            ["series_id"],
            ["book_series.id"],
            name="fk_series_memberships_series_id_book_series",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["book_id"],
            ["books.id"],
            name="fk_series_memberships_book_id_books",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("book_id", name="pk_series_memberships"),
        sa.UniqueConstraint(
            "series_id",
            "position",
            name="uq_series_memberships_series_position",
        ),
    )
    op.create_index(
        "ix_series_memberships_series_id",
        "series_memberships",
        ["series_id"],
    )

    op.create_table(
        "reader_settings",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("font_size", sa.Integer(), server_default="18", nullable=False),
        sa.Column("line_height", sa.Float(), server_default="1.8", nullable=False),
        sa.Column("content_width", sa.Integer(), server_default="760", nullable=False),
        sa.Column(
            "font_family",
            reader_font_family,
            server_default="serif",
            nullable=False,
        ),
        sa.Column("theme", reader_theme, server_default="light", nullable=False),
        timestamp("created_at"),
        timestamp("updated_at"),
        sa.CheckConstraint(
            "font_size BETWEEN 12 AND 36",
            name="ck_reader_settings_font_size_range",
        ),
        sa.CheckConstraint(
            "line_height BETWEEN 1.2 AND 2.8",
            name="ck_reader_settings_line_height_range",
        ),
        sa.CheckConstraint(
            "content_width BETWEEN 480 AND 1200",
            name="ck_reader_settings_content_width_range",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_reader_settings_user_id_users",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("user_id", name="pk_reader_settings"),
    )

    op.create_table(
        "reading_progresses",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("edition_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", reading_status, server_default="not_started", nullable=False),
        sa.Column("section_id", sa.String(length=100), nullable=True),
        sa.Column("block_id", sa.String(length=100), nullable=True),
        sa.Column("section_progress", sa.Float(), server_default="0", nullable=False),
        sa.Column("overall_progress", sa.Float(), server_default="0", nullable=False),
        sa.Column("edition_file_revision", sa.Integer(), nullable=True),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("updated_device_id", postgresql.UUID(as_uuid=True), nullable=True),
        timestamp("last_read_at"),
        timestamp("created_at"),
        timestamp("updated_at"),
        sa.CheckConstraint(
            "section_progress BETWEEN 0 AND 1",
            name="ck_reading_progresses_section_progress_range",
        ),
        sa.CheckConstraint(
            "overall_progress BETWEEN 0 AND 1",
            name="ck_reading_progresses_overall_progress_range",
        ),
        sa.CheckConstraint(
            "edition_file_revision IS NULL OR edition_file_revision >= 1",
            name="ck_reading_progresses_file_revision_positive",
        ),
        sa.CheckConstraint(
            "version >= 1",
            name="ck_reading_progresses_version_positive",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_reading_progresses_user_id_users",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["edition_id"],
            ["book_editions.id"],
            name="fk_reading_progresses_edition_id_book_editions",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["updated_device_id"],
            ["devices.id"],
            name="fk_reading_progresses_updated_device_id_devices",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("user_id", "edition_id", name="pk_reading_progresses"),
    )
    op.create_index(
        "ix_reading_progresses_user_last_read",
        "reading_progresses",
        ["user_id", "last_read_at"],
    )
    op.create_index(
        "ix_reading_progresses_edition_id",
        "reading_progresses",
        ["edition_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_reading_progresses_edition_id", table_name="reading_progresses")
    op.drop_index("ix_reading_progresses_user_last_read", table_name="reading_progresses")
    op.drop_table("reading_progresses")
    op.drop_table("reader_settings")
    op.drop_index("ix_series_memberships_series_id", table_name="series_memberships")
    op.drop_table("series_memberships")
    op.drop_index("ix_book_series_owner_updated", table_name="book_series")
    op.drop_index("ix_book_series_owner_user_id", table_name="book_series")
    op.drop_table("book_series")

    bind = op.get_bind()
    reader_font_family.drop(bind, checkfirst=True)
    reader_theme.drop(bind, checkfirst=True)
    reading_status.drop(bind, checkfirst=True)
