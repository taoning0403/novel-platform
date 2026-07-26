"""Add encrypted Provider credential versions and scoped translation Runs.

Revision ID: 20260726_0007
Revises: 20260723_0006
Create Date: 2026-07-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260726_0007"
down_revision: str | None = "20260723_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "provider_credential_versions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "provider",
            sa.String(length=32),
            server_default="openai_compatible",
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column(
            "algorithm",
            sa.String(length=32),
            server_default="aes-256-gcm-v1",
            nullable=False,
        ),
        sa.Column("nonce", sa.LargeBinary(), nullable=False),
        sa.Column("ciphertext", sa.LargeBinary(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "provider = 'openai_compatible'",
            name="ck_provider_credential_versions_provider_openai_compatible",
        ),
        sa.CheckConstraint(
            "version >= 1",
            name="ck_provider_credential_versions_version_positive",
        ),
        sa.CheckConstraint(
            "octet_length(nonce) = 12",
            name="ck_provider_credential_versions_nonce_length",
        ),
        sa.CheckConstraint(
            "octet_length(ciphertext) >= 17",
            name="ck_provider_credential_versions_ciphertext_has_tag",
        ),
        sa.CheckConstraint(
            "algorithm = 'aes-256-gcm-v1'",
            name="ck_provider_credential_versions_algorithm_aes_256_gcm_v1",
        ),
        sa.CheckConstraint(
            "retired_at IS NULL OR retired_at >= created_at",
            name="ck_provider_credential_versions_retired_after_creation",
        ),
        sa.CheckConstraint(
            "revoked_at IS NULL OR revoked_at >= created_at",
            name="ck_provider_credential_versions_revoked_after_creation",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_provider_credential_versions_user_id_users",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_provider_credential_versions"),
        sa.UniqueConstraint(
            "user_id",
            "provider",
            "version",
            name="uq_provider_credential_versions_user_provider_version",
        ),
    )
    op.create_index(
        "ix_provider_credential_versions_user_id",
        "provider_credential_versions",
        ["user_id"],
    )
    op.create_index(
        "ix_provider_credential_versions_user_created",
        "provider_credential_versions",
        ["user_id", "created_at"],
    )
    op.create_index(
        "uq_provider_credential_versions_current",
        "provider_credential_versions",
        ["user_id", "provider"],
        unique=True,
        postgresql_where=sa.text("retired_at IS NULL AND revoked_at IS NULL"),
    )

    op.create_table(
        "provider_usage_records",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "provider_credential_version_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("model", sa.String(length=120), nullable=False),
        sa.Column("prompt_tokens", sa.Integer(), nullable=False),
        sa.Column("completion_tokens", sa.Integer(), nullable=False),
        sa.Column("total_tokens", sa.Integer(), nullable=False),
        sa.Column("remote_job_id", sa.String(length=128), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "prompt_tokens >= 0",
            name="ck_provider_usage_records_prompt_tokens_nonnegative",
        ),
        sa.CheckConstraint(
            "completion_tokens >= 0",
            name="ck_provider_usage_records_completion_tokens_nonnegative",
        ),
        sa.CheckConstraint(
            "total_tokens >= 0",
            name="ck_provider_usage_records_total_tokens_nonnegative",
        ),
        sa.CheckConstraint(
            "total_tokens >= prompt_tokens AND total_tokens >= completion_tokens",
            name="ck_provider_usage_records_total_tokens_consistent",
        ),
        sa.CheckConstraint(
            "length(btrim(model)) > 0",
            name="ck_provider_usage_records_model_not_blank",
        ),
        sa.ForeignKeyConstraint(
            ["provider_credential_version_id"],
            ["provider_credential_versions.id"],
            name="fk_provider_usage_records_provider_credential_version_id",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_provider_usage_records"),
    )
    op.create_index(
        "ix_provider_usage_records_credential_created",
        "provider_usage_records",
        ["provider_credential_version_id", "created_at"],
    )

    # v0.9 Runs predate per-actor Provider billing and cannot be assigned a truthful
    # credential version. Refuse the migration rather than fabricating ownership or
    # silently deleting durable orchestration history.
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM edition_translation_runs) THEN
                RAISE EXCEPTION 'v0100_preflight_unscoped_translation_runs';
            END IF;
        END $$;
        """
    )
    op.add_column(
        "edition_translation_runs",
        sa.Column(
            "provider_credential_version_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
    )
    op.create_foreign_key(
        "fk_edition_translation_runs_provider_credential_version_id",
        "edition_translation_runs",
        "provider_credential_versions",
        ["provider_credential_version_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_edition_translation_runs_provider_credential_version_id",
        "edition_translation_runs",
        ["provider_credential_version_id"],
    )
    op.create_index(
        "uq_translation_runs_credential_bootstrap",
        "edition_translation_runs",
        ["provider_credential_version_id"],
        unique=True,
        postgresql_where=sa.text("remote_job_id IS NULL AND status = 'preparing'"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_translation_runs_credential_bootstrap",
        table_name="edition_translation_runs",
    )
    op.drop_index(
        "ix_edition_translation_runs_provider_credential_version_id",
        table_name="edition_translation_runs",
    )
    op.drop_constraint(
        "fk_edition_translation_runs_provider_credential_version_id",
        "edition_translation_runs",
        type_="foreignkey",
    )
    op.drop_column("edition_translation_runs", "provider_credential_version_id")
    op.drop_index(
        "ix_provider_usage_records_credential_created",
        table_name="provider_usage_records",
    )
    op.drop_table("provider_usage_records")
    op.drop_index(
        "uq_provider_credential_versions_current",
        table_name="provider_credential_versions",
    )
    op.drop_index(
        "ix_provider_credential_versions_user_created",
        table_name="provider_credential_versions",
    )
    op.drop_index(
        "ix_provider_credential_versions_user_id",
        table_name="provider_credential_versions",
    )
    op.drop_table("provider_credential_versions")
