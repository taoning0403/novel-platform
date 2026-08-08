"""Allow EPUB sources in Translation Runs.

Revision ID: 20260727_0009
Revises: 20260726_0008
Create Date: 2026-07-27
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260727_0009"
down_revision: str | None = "20260726_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(
        op.f("ck_edition_translation_runs_ck_translation_runs_source_format"),
        "edition_translation_runs",
        type_="check",
    )
    op.create_check_constraint(
        "source_format_supported",
        "edition_translation_runs",
        "source_format IN ('epub', 'txt')",
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM edition_translation_runs
                WHERE source_format = 'epub'
            ) THEN
                RAISE EXCEPTION 'epub_translation_runs_cannot_downgrade';
            END IF;
        END $$;
        """
    )
    op.drop_constraint(
        op.f("ck_edition_translation_runs_source_format_supported"),
        "edition_translation_runs",
        type_="check",
    )
    op.create_check_constraint(
        op.f("ck_edition_translation_runs_ck_translation_runs_source_format"),
        "edition_translation_runs",
        "source_format = 'txt'",
    )
