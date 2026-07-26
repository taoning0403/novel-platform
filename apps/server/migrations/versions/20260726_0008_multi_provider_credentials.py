"""Add version-bound multi-Provider routing configuration.

Revision ID: 20260726_0008
Revises: 20260726_0007
Create Date: 2026-07-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260726_0008"
down_revision: str | None = "20260726_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "provider_credential_versions",
        sa.Column("provider_name", sa.String(length=120), nullable=True),
    )
    op.add_column(
        "provider_credential_versions",
        sa.Column(
            "base_url",
            sa.String(length=2048),
            server_default="https://api.openai.com/v1",
            nullable=False,
        ),
    )
    op.add_column(
        "provider_credential_versions",
        sa.Column(
            "thinking_enabled",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
    )
    op.add_column(
        "provider_credential_versions",
        sa.Column(
            "model",
            sa.String(length=120),
            server_default="gpt-4.1-mini",
            nullable=False,
        ),
    )

    op.drop_constraint(
        "ck_provider_credential_versions_provider_openai_compatible",
        "provider_credential_versions",
        type_="check",
    )
    op.drop_constraint(
        "ck_provider_credential_versions_algorithm_aes_256_gcm_v1",
        "provider_credential_versions",
        type_="check",
    )
    op.drop_constraint(
        "uq_provider_credential_versions_user_provider_version",
        "provider_credential_versions",
        type_="unique",
    )
    op.drop_index(
        "uq_provider_credential_versions_current",
        table_name="provider_credential_versions",
    )

    op.create_check_constraint(
        "provider_known",
        "provider_credential_versions",
        "provider IN ('openai_compatible', 'deepseek', 'kimi', 'custom')",
    )
    op.create_check_constraint(
        "provider_name_matches_provider",
        "provider_credential_versions",
        "(provider = 'custom' AND provider_name IS NOT NULL "
        "AND length(btrim(provider_name)) > 0) "
        "OR (provider <> 'custom' AND provider_name IS NULL)",
    )
    op.create_check_constraint(
        "base_url_not_blank",
        "provider_credential_versions",
        "length(btrim(base_url)) > 0",
    )
    op.create_check_constraint(
        "model_not_blank",
        "provider_credential_versions",
        "length(btrim(model)) > 0",
    )
    op.create_check_constraint(
        "algorithm_supported",
        "provider_credential_versions",
        "algorithm IN ('aes-256-gcm-v1', 'aes-256-gcm-v2')",
    )
    op.create_unique_constraint(
        "uq_provider_credential_versions_user_version",
        "provider_credential_versions",
        ["user_id", "version"],
    )
    op.create_index(
        "uq_provider_credential_versions_current",
        "provider_credential_versions",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("retired_at IS NULL AND revoked_at IS NULL"),
    )
    op.alter_column(
        "provider_credential_versions",
        "algorithm",
        server_default="aes-256-gcm-v2",
        existing_type=sa.String(length=32),
        existing_nullable=False,
    )
    op.alter_column(
        "provider_credential_versions",
        "base_url",
        server_default=None,
        existing_type=sa.String(length=2048),
        existing_nullable=False,
    )
    op.alter_column(
        "provider_credential_versions",
        "model",
        server_default=None,
        existing_type=sa.String(length=120),
        existing_nullable=False,
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM provider_credential_versions
                WHERE provider <> 'openai_compatible'
                   OR algorithm <> 'aes-256-gcm-v1'
            ) THEN
                RAISE EXCEPTION 'v0100_multi_provider_credentials_cannot_downgrade';
            END IF;
        END $$;
        """
    )
    op.alter_column(
        "provider_credential_versions",
        "algorithm",
        server_default="aes-256-gcm-v1",
        existing_type=sa.String(length=32),
        existing_nullable=False,
    )
    op.drop_index(
        "uq_provider_credential_versions_current",
        table_name="provider_credential_versions",
    )
    op.drop_constraint(
        "uq_provider_credential_versions_user_version",
        "provider_credential_versions",
        type_="unique",
    )
    op.drop_constraint(
        "ck_provider_credential_versions_algorithm_supported",
        "provider_credential_versions",
        type_="check",
    )
    op.drop_constraint(
        "ck_provider_credential_versions_model_not_blank",
        "provider_credential_versions",
        type_="check",
    )
    op.drop_constraint(
        "ck_provider_credential_versions_base_url_not_blank",
        "provider_credential_versions",
        type_="check",
    )
    op.drop_constraint(
        "ck_provider_credential_versions_provider_name_matches_provider",
        "provider_credential_versions",
        type_="check",
    )
    op.drop_constraint(
        "ck_provider_credential_versions_provider_known",
        "provider_credential_versions",
        type_="check",
    )
    op.create_check_constraint(
        "provider_openai_compatible",
        "provider_credential_versions",
        "provider = 'openai_compatible'",
    )
    op.create_check_constraint(
        "algorithm_aes_256_gcm_v1",
        "provider_credential_versions",
        "algorithm = 'aes-256-gcm-v1'",
    )
    op.create_unique_constraint(
        "uq_provider_credential_versions_user_provider_version",
        "provider_credential_versions",
        ["user_id", "provider", "version"],
    )
    op.create_index(
        "uq_provider_credential_versions_current",
        "provider_credential_versions",
        ["user_id", "provider"],
        unique=True,
        postgresql_where=sa.text("retired_at IS NULL AND revoked_at IS NULL"),
    )
    op.drop_column("provider_credential_versions", "model")
    op.drop_column("provider_credential_versions", "thinking_enabled")
    op.drop_column("provider_credential_versions", "base_url")
    op.drop_column("provider_credential_versions", "provider_name")
