"""Create books and book editions.

Revision ID: 20260710_0001
Revises:
Create Date: 2026-07-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260710_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

content_role = postgresql.ENUM("source", "translation", name="content_role", create_type=False)
translation_origin = postgresql.ENUM(
    "ai", "human", "mixed", "unknown", name="translation_origin", create_type=False
)
creation_method = postgresql.ENUM(
    "uploaded", "generated", "edited", "converted", name="creation_method", create_type=False
)
edition_status = postgresql.ENUM(
    "draft", "ready", "archived", name="edition_status", create_type=False
)


def upgrade() -> None:
    bind = op.get_bind()
    content_role.create(bind, checkfirst=True)
    translation_origin.create(bind, checkfirst=True)
    creation_method.create(bind, checkfirst=True)
    edition_status.create(bind, checkfirst=True)

    op.create_table(
        "books",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("canonical_title", sa.String(), nullable=False),
        sa.Column("canonical_author", sa.String(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
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
        sa.CheckConstraint("length(btrim(canonical_title)) > 0", name="ck_books_title_not_blank"),
        sa.PrimaryKeyConstraint("id", name="pk_books"),
    )
    op.create_table(
        "book_editions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("book_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("language", sa.String(), nullable=False),
        sa.Column("content_role", content_role, nullable=False),
        sa.Column("translation_origin", translation_origin, nullable=True),
        sa.Column("creation_method", creation_method, nullable=False),
        sa.Column("source_edition_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("supersedes_edition_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("status", edition_status, server_default="draft", nullable=False),
        sa.Column("revision", sa.Integer(), server_default="1", nullable=False),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
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
        sa.CheckConstraint("length(btrim(title)) > 0", name="ck_book_editions_title_not_blank"),
        sa.CheckConstraint(
            "length(btrim(language)) > 0", name="ck_book_editions_language_not_blank"
        ),
        sa.CheckConstraint("revision >= 1", name="ck_book_editions_revision_at_least_one"),
        sa.CheckConstraint(
            "source_edition_id IS NULL OR source_edition_id <> id",
            name="ck_book_editions_source_not_self",
        ),
        sa.CheckConstraint(
            "supersedes_edition_id IS NULL OR supersedes_edition_id <> id",
            name="ck_book_editions_supersedes_not_self",
        ),
        sa.CheckConstraint(
            "(content_role = 'source' AND translation_origin IS NULL "
            "AND source_edition_id IS NULL) OR "
            "(content_role = 'translation' AND translation_origin IS NOT NULL)",
            name="ck_book_editions_role_origin_and_source_consistent",
        ),
        sa.ForeignKeyConstraint(
            ["book_id"], ["books.id"], name="fk_book_editions_book_id_books", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["source_edition_id"],
            ["book_editions.id"],
            name="fk_book_editions_source_edition_id_book_editions",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["supersedes_edition_id"],
            ["book_editions.id"],
            name="fk_book_editions_supersedes_edition_id_book_editions",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_book_editions"),
    )
    op.create_index("ix_book_editions_book_id", "book_editions", ["book_id"], unique=False)
    op.create_index(
        "ix_book_editions_book_created", "book_editions", ["book_id", "created_at"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_book_editions_book_created", table_name="book_editions")
    op.drop_index("ix_book_editions_book_id", table_name="book_editions")
    op.drop_table("book_editions")
    op.drop_table("books")
    bind = op.get_bind()
    edition_status.drop(bind, checkfirst=True)
    creation_method.drop(bind, checkfirst=True)
    translation_origin.drop(bind, checkfirst=True)
    content_role.drop(bind, checkfirst=True)
