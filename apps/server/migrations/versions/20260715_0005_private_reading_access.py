"""Add private reading access, passkeys, site settings, and security audit state.

Revision ID: 20260715_0005
Revises: 20260714_0004
Create Date: 2026-07-15
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260715_0005"
down_revision: str | None = "20260714_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

access_credential_status = postgresql.ENUM(
    "active", "suspended", "revoked", name="access_credential_status", create_type=False
)
admin_recovery_purpose = postgresql.ENUM(
    "initialize",
    "recovery",
    "credential_reset",
    name="admin_recovery_purpose",
    create_type=False,
)
webauthn_challenge_purpose = postgresql.ENUM(
    "registration",
    "authentication",
    name="webauthn_challenge_purpose",
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
    access_credential_status.create(bind, checkfirst=True)
    admin_recovery_purpose.create(bind, checkfirst=True)
    webauthn_challenge_purpose.create(bind, checkfirst=True)

    op.drop_constraint("ck_users_active_user_has_password", "users", type_="check")
    op.add_column("users", sa.Column("admin_note", sa.Text(), nullable=True))

    op.create_table(
        "site_settings",
        sa.Column("id", sa.Integer(), server_default="1", nullable=False),
        sa.Column("site_name", sa.String(length=200), nullable=False),
        sa.Column("purpose_statement", sa.Text(), nullable=False),
        sa.Column("privacy_statement", sa.Text(), nullable=False),
        sa.Column("icp_registration_number", sa.String(length=100), nullable=True),
        sa.Column("icp_registration_url", sa.String(length=500), nullable=True),
        sa.Column("default_reader_max_devices", sa.Integer(), server_default="3", nullable=False),
        sa.Column("audit_retention_days", sa.Integer(), server_default="90", nullable=False),
        sa.Column("library_owner_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("admin_locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("migration_completed_at", sa.DateTime(timezone=True), nullable=True),
        timestamp("created_at"),
        timestamp("updated_at"),
        sa.CheckConstraint("id = 1", name="ck_site_settings_singleton"),
        sa.CheckConstraint(
            "length(btrim(site_name)) > 0", name="ck_site_settings_site_name_not_blank"
        ),
        sa.CheckConstraint(
            "length(btrim(purpose_statement)) > 0", name="ck_site_settings_purpose_not_blank"
        ),
        sa.CheckConstraint(
            "length(btrim(privacy_statement)) > 0", name="ck_site_settings_privacy_not_blank"
        ),
        sa.CheckConstraint(
            "default_reader_max_devices >= 1",
            name="ck_site_settings_default_devices_positive",
        ),
        sa.CheckConstraint("audit_retention_days >= 1", name="ck_site_settings_retention_positive"),
        sa.ForeignKeyConstraint(
            ["library_owner_user_id"],
            ["users.id"],
            name="fk_site_settings_library_owner_user_id_users",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_site_settings"),
        sa.UniqueConstraint("library_owner_user_id", name="uq_site_settings_library_owner_user_id"),
    )
    op.execute(
        sa.text(
            "INSERT INTO site_settings "
            "(id, site_name, purpose_statement, privacy_statement) "
            "VALUES (1, :site_name, :purpose, :privacy)"
        ).bindparams(
            site_name="个人数字阅读与藏书整理",
            purpose=(
                "本站为个人非经营性数字阅读与藏书整理站点，主要用于个人学习、"
                "阅读记录及合法电子资料管理，仅限经授权的少量访问者使用。"
            ),
            privacy=(
                "为保障账号和设备安全，系统会在最小范围内记录登录时间、IP、"
                "User-Agent 摘要和安全事件，并按配置期限清理。"
            ),
        )
    )

    op.create_table(
        "reader_access_credentials",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("credential_hint", sa.String(length=20), nullable=False),
        sa.Column("status", access_credential_status, server_default="active", nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("allow_new_devices", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("max_devices", sa.Integer(), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("suspended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reissued_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by_admin_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("updated_by_admin_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("replaced_by_credential_id", postgresql.UUID(as_uuid=True), nullable=True),
        timestamp("created_at"),
        timestamp("updated_at"),
        sa.CheckConstraint(
            "length(token_hash) = 64",
            name="ck_reader_access_credentials_token_hash_length",
        ),
        sa.CheckConstraint(
            "length(btrim(credential_hint)) > 0",
            name="ck_reader_access_credentials_hint_not_blank",
        ),
        sa.CheckConstraint(
            "max_devices >= 1",
            name="ck_reader_access_credentials_max_devices_positive",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_reader_access_credentials_user_id_users",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_admin_id"],
            ["users.id"],
            name="fk_reader_access_credentials_created_by_admin_id_users",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["updated_by_admin_id"],
            ["users.id"],
            name="fk_reader_access_credentials_updated_by_admin_id_users",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["replaced_by_credential_id"],
            ["reader_access_credentials.id"],
            name="fk_reader_credentials_replaced_by",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_reader_access_credentials"),
        sa.UniqueConstraint("token_hash", name="uq_reader_access_credentials_token_hash"),
    )
    op.create_index(
        "ix_reader_access_credentials_user_id", "reader_access_credentials", ["user_id"]
    )
    op.create_index(
        "ix_reader_access_credentials_user_created",
        "reader_access_credentials",
        ["user_id", "created_at"],
    )
    op.create_index(
        "uq_reader_access_credentials_current",
        "reader_access_credentials",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("status <> 'revoked'"),
    )

    op.create_table(
        "admin_recovery_credentials",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("credential_hint", sa.String(length=20), nullable=False),
        sa.Column("purpose", admin_recovery_purpose, nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        timestamp("created_at"),
        sa.CheckConstraint(
            "length(token_hash) = 64",
            name="ck_admin_recovery_credentials_token_hash_length",
        ),
        sa.CheckConstraint(
            "length(btrim(credential_hint)) > 0",
            name="ck_admin_recovery_credentials_hint_not_blank",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_admin_recovery_credentials_user_id_users",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_admin_recovery_credentials"),
        sa.UniqueConstraint("token_hash", name="uq_admin_recovery_credentials_token_hash"),
    )
    op.create_index(
        "ix_admin_recovery_credentials_user_id", "admin_recovery_credentials", ["user_id"]
    )
    op.create_index(
        "ix_admin_recovery_credentials_user_created",
        "admin_recovery_credentials",
        ["user_id", "created_at"],
    )

    op.create_table(
        "admin_passkeys",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("credential_id", sa.LargeBinary(), nullable=False),
        sa.Column("public_key", sa.LargeBinary(), nullable=False),
        sa.Column("sign_count", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("transports", postgresql.JSONB(), server_default="[]", nullable=False),
        sa.Column("device_type", sa.String(length=50), nullable=True),
        sa.Column("backed_up", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        timestamp("created_at"),
        timestamp("updated_at"),
        sa.CheckConstraint("length(btrim(name)) > 0", name="ck_admin_passkeys_name_not_blank"),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_admin_passkeys_user_id_users",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_admin_passkeys"),
        sa.UniqueConstraint("credential_id", name="uq_admin_passkeys_credential_id"),
    )
    op.create_index("ix_admin_passkeys_user_id", "admin_passkeys", ["user_id"])
    op.create_index("ix_admin_passkeys_user_created", "admin_passkeys", ["user_id", "created_at"])

    op.create_table(
        "webauthn_challenges",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("challenge", sa.LargeBinary(), nullable=False),
        sa.Column("purpose", webauthn_challenge_purpose, nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("expected_origin", sa.String(length=500), nullable=False),
        sa.Column("rp_id", sa.String(length=255), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        timestamp("created_at"),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_webauthn_challenges_user_id_users",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_webauthn_challenges"),
        sa.UniqueConstraint("challenge", name="uq_webauthn_challenges_challenge"),
    )
    op.create_index("ix_webauthn_challenges_user_id", "webauthn_challenges", ["user_id"])
    op.create_index("ix_webauthn_challenges_expires", "webauthn_challenges", ["expires_at"])

    op.drop_constraint("uq_devices_user_client_instance", "devices", type_="unique")
    op.add_column(
        "devices",
        sa.Column("access_credential_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column("devices", sa.Column("device_secret_hash", sa.String(length=64), nullable=True))
    op.add_column("devices", sa.Column("first_authorized_ip", sa.String(length=64), nullable=True))
    op.add_column("devices", sa.Column("last_used_ip", sa.String(length=64), nullable=True))
    op.add_column("devices", sa.Column("user_agent_summary", sa.String(length=255), nullable=True))
    op.create_check_constraint(
        "ck_devices_device_secret_hash_length",
        "devices",
        "device_secret_hash IS NULL OR length(device_secret_hash) = 64",
    )
    op.create_foreign_key(
        "fk_devices_access_credential",
        "devices",
        "reader_access_credentials",
        ["access_credential_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_devices_access_credential_id", "devices", ["access_credential_id"])
    op.create_index("ix_devices_device_secret_hash", "devices", ["device_secret_hash"], unique=True)
    op.create_index("ix_devices_user_last_seen", "devices", ["user_id", "last_seen_at"])

    op.add_column(
        "auth_sessions",
        sa.Column("access_credential_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "auth_sessions", sa.Column("passkey_id", postgresql.UUID(as_uuid=True), nullable=True)
    )
    op.add_column(
        "auth_sessions",
        sa.Column("recovery_credential_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "auth_sessions",
        sa.Column("recovery_mode", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.create_foreign_key(
        "fk_auth_sessions_access_credential",
        "auth_sessions",
        "reader_access_credentials",
        ["access_credential_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_auth_sessions_passkey_id_admin_passkeys",
        "auth_sessions",
        "admin_passkeys",
        ["passkey_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_auth_sessions_recovery_credential",
        "auth_sessions",
        "admin_recovery_credentials",
        ["recovery_credential_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_auth_sessions_access_credential_id", "auth_sessions", ["access_credential_id"]
    )
    op.create_index("ix_auth_sessions_passkey_id", "auth_sessions", ["passkey_id"])
    op.create_index(
        "ix_auth_sessions_recovery_credential_id", "auth_sessions", ["recovery_credential_id"]
    )

    op.add_column(
        "auth_audit_events",
        sa.Column("access_credential_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "auth_audit_events", sa.Column("passkey_id", postgresql.UUID(as_uuid=True), nullable=True)
    )
    op.add_column("auth_audit_events", sa.Column("client_ip", sa.String(length=64), nullable=True))
    op.add_column(
        "auth_audit_events",
        sa.Column("user_agent_summary", sa.String(length=255), nullable=True),
    )
    op.create_foreign_key(
        "fk_auth_audit_access_credential",
        "auth_audit_events",
        "reader_access_credentials",
        ["access_credential_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_auth_audit_events_passkey_id_admin_passkeys",
        "auth_audit_events",
        "admin_passkeys",
        ["passkey_id"],
        ["id"],
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_auth_audit_events_passkey_id_admin_passkeys", "auth_audit_events", type_="foreignkey"
    )
    op.drop_constraint(
        "fk_auth_audit_access_credential",
        "auth_audit_events",
        type_="foreignkey",
    )
    op.drop_column("auth_audit_events", "user_agent_summary")
    op.drop_column("auth_audit_events", "client_ip")
    op.drop_column("auth_audit_events", "passkey_id")
    op.drop_column("auth_audit_events", "access_credential_id")

    op.drop_index("ix_auth_sessions_recovery_credential_id", table_name="auth_sessions")
    op.drop_index("ix_auth_sessions_passkey_id", table_name="auth_sessions")
    op.drop_index("ix_auth_sessions_access_credential_id", table_name="auth_sessions")
    op.drop_constraint(
        "fk_auth_sessions_recovery_credential",
        "auth_sessions",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_auth_sessions_passkey_id_admin_passkeys", "auth_sessions", type_="foreignkey"
    )
    op.drop_constraint(
        "fk_auth_sessions_access_credential",
        "auth_sessions",
        type_="foreignkey",
    )
    op.drop_column("auth_sessions", "recovery_mode")
    op.drop_column("auth_sessions", "recovery_credential_id")
    op.drop_column("auth_sessions", "passkey_id")
    op.drop_column("auth_sessions", "access_credential_id")

    op.drop_index("ix_devices_user_last_seen", table_name="devices")
    op.drop_index("ix_devices_device_secret_hash", table_name="devices")
    op.drop_index("ix_devices_access_credential_id", table_name="devices")
    op.drop_constraint(
        "fk_devices_access_credential",
        "devices",
        type_="foreignkey",
    )
    op.drop_constraint("ck_devices_device_secret_hash_length", "devices", type_="check")
    op.drop_column("devices", "user_agent_summary")
    op.drop_column("devices", "last_used_ip")
    op.drop_column("devices", "first_authorized_ip")
    op.drop_column("devices", "device_secret_hash")
    op.drop_column("devices", "access_credential_id")
    op.create_unique_constraint(
        "uq_devices_user_client_instance", "devices", ["user_id", "client_instance_id"]
    )

    op.drop_index("ix_webauthn_challenges_expires", table_name="webauthn_challenges")
    op.drop_index("ix_webauthn_challenges_user_id", table_name="webauthn_challenges")
    op.drop_table("webauthn_challenges")
    op.drop_index("ix_admin_passkeys_user_created", table_name="admin_passkeys")
    op.drop_index("ix_admin_passkeys_user_id", table_name="admin_passkeys")
    op.drop_table("admin_passkeys")
    op.drop_index(
        "ix_admin_recovery_credentials_user_created", table_name="admin_recovery_credentials"
    )
    op.drop_index("ix_admin_recovery_credentials_user_id", table_name="admin_recovery_credentials")
    op.drop_table("admin_recovery_credentials")
    op.drop_index("uq_reader_access_credentials_current", table_name="reader_access_credentials")
    op.drop_index(
        "ix_reader_access_credentials_user_created", table_name="reader_access_credentials"
    )
    op.drop_index("ix_reader_access_credentials_user_id", table_name="reader_access_credentials")
    op.drop_table("reader_access_credentials")
    op.drop_table("site_settings")

    op.drop_column("users", "admin_note")
    op.create_check_constraint(
        "ck_users_active_user_has_password",
        "users",
        "status = 'pending_setup' OR password_hash IS NOT NULL",
    )

    bind = op.get_bind()
    webauthn_challenge_purpose.drop(bind, checkfirst=True)
    admin_recovery_purpose.drop(bind, checkfirst=True)
    access_credential_status.drop(bind, checkfirst=True)
