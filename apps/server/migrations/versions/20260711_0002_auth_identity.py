"""Add users, devices, sessions, ownership, and edition preferences.

Revision ID: 20260711_0002
Revises: 20260710_0001
Create Date: 2026-07-11
"""

from collections.abc import Sequence
from uuid import UUID

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260711_0002"
down_revision: str | None = "20260710_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PENDING_SETUP_USER_ID = UUID("00000000-0000-0000-0000-000000000001")

user_role = postgresql.ENUM("admin", "member", name="user_role", create_type=False)
user_status = postgresql.ENUM(
    "pending_setup", "active", "disabled", name="user_status", create_type=False
)
device_platform = postgresql.ENUM(
    "web",
    "windows",
    "macos",
    "linux",
    "android",
    "ipados",
    "unknown",
    name="device_platform",
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
    user_role.create(bind, checkfirst=True)
    user_status.create(bind, checkfirst=True)
    device_platform.create(bind, checkfirst=True)

    op.create_table(
        "users",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("username", sa.String(length=64), nullable=False),
        sa.Column("normalized_username", sa.String(length=64), nullable=False),
        sa.Column("display_name", sa.String(length=100), nullable=False),
        sa.Column("role", user_role, nullable=False),
        sa.Column("status", user_status, nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=True),
        sa.Column("password_changed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        timestamp("created_at"),
        timestamp("updated_at"),
        sa.CheckConstraint(
            "status = 'pending_setup' OR password_hash IS NOT NULL",
            name="ck_users_active_user_has_password",
        ),
        sa.CheckConstraint("length(btrim(username)) > 0", name="ck_users_username_not_blank"),
        sa.CheckConstraint(
            "length(btrim(display_name)) > 0", name="ck_users_display_name_not_blank"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_users"),
        sa.UniqueConstraint("normalized_username", name="uq_users_normalized_username"),
    )
    op.execute(
        sa.text(
            "INSERT INTO users "
            "(id, username, normalized_username, display_name, role, status) "
            "VALUES (:id, '__pending_setup__', '__pending_setup__', "
            "'Pending setup', 'admin', 'pending_setup')"
        ).bindparams(id=PENDING_SETUP_USER_ID)
    )

    op.create_table(
        "devices",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("client_instance_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("platform", device_platform, nullable=False),
        sa.Column("app_version", sa.String(length=100), nullable=True),
        timestamp("first_seen_at"),
        timestamp("last_seen_at"),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        timestamp("created_at"),
        timestamp("updated_at"),
        sa.CheckConstraint("length(btrim(name)) > 0", name="ck_devices_name_not_blank"),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_devices_user_id_users", ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_devices"),
        sa.UniqueConstraint(
            "user_id", "client_instance_id", name="uq_devices_user_client_instance"
        ),
    )
    op.create_index("ix_devices_user_id", "devices", ["user_id"])

    op.create_table(
        "auth_sessions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("device_id", postgresql.UUID(as_uuid=True), nullable=False),
        timestamp("created_at"),
        timestamp("last_seen_at"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoke_reason", sa.String(length=100), nullable=True),
        sa.ForeignKeyConstraint(
            ["device_id"],
            ["devices.id"],
            name="fk_auth_sessions_device_id_devices",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_auth_sessions_user_id_users",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_auth_sessions"),
    )
    op.create_index("ix_auth_sessions_user_id", "auth_sessions", ["user_id"])
    op.create_index("ix_auth_sessions_device_id", "auth_sessions", ["device_id"])
    op.create_index("ix_auth_sessions_user_device", "auth_sessions", ["user_id", "device_id"])

    op.create_table(
        "refresh_tokens",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        timestamp("issued_at"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("replaced_by_token_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["replaced_by_token_id"],
            ["refresh_tokens.id"],
            name="fk_refresh_tokens_replaced_by_token_id_refresh_tokens",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["auth_sessions.id"],
            name="fk_refresh_tokens_session_id_auth_sessions",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_refresh_tokens"),
        sa.UniqueConstraint("token_hash", name="uq_refresh_tokens_token_hash"),
    )
    op.create_index("ix_refresh_tokens_session_id", "refresh_tokens", ["session_id"])

    op.create_table(
        "login_throttles",
        sa.Column("key_hash", sa.String(length=64), nullable=False),
        sa.Column("failure_count", sa.Integer(), nullable=False),
        sa.Column("window_started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("blocked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "failure_count >= 0", name="ck_login_throttles_failure_count_nonnegative"
        ),
        sa.PrimaryKeyConstraint("key_hash", name="pk_login_throttles"),
    )

    op.create_table(
        "auth_audit_events",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column("outcome", sa.String(length=32), nullable=False),
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("subject_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("device_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        timestamp("created_at"),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["users.id"],
            name="fk_auth_audit_events_actor_user_id_users",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["device_id"],
            ["devices.id"],
            name="fk_auth_audit_events_device_id_devices",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["auth_sessions.id"],
            name="fk_auth_audit_events_session_id_auth_sessions",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["subject_user_id"],
            ["users.id"],
            name="fk_auth_audit_events_subject_user_id_users",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_auth_audit_events"),
    )
    op.create_index("ix_auth_audit_events_actor_user_id", "auth_audit_events", ["actor_user_id"])
    op.create_index(
        "ix_auth_audit_events_subject_user_id", "auth_audit_events", ["subject_user_id"]
    )
    op.create_index(
        "ix_auth_audit_events_type_created", "auth_audit_events", ["event_type", "created_at"]
    )

    op.add_column("books", sa.Column("owner_user_id", postgresql.UUID(as_uuid=True)))
    op.execute(
        sa.text("UPDATE books SET owner_user_id = :id WHERE owner_user_id IS NULL").bindparams(
            id=PENDING_SETUP_USER_ID
        )
    )
    op.alter_column("books", "owner_user_id", nullable=False)
    op.create_foreign_key(
        "fk_books_owner_user_id_users",
        "books",
        "users",
        ["owner_user_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_books_owner_user_id", "books", ["owner_user_id"])

    op.create_table(
        "user_book_preferences",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("book_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("preferred_edition_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("last_opened_edition_id", postgresql.UUID(as_uuid=True), nullable=True),
        timestamp("created_at"),
        timestamp("updated_at"),
        sa.ForeignKeyConstraint(
            ["book_id"],
            ["books.id"],
            name="fk_user_book_preferences_book_id_books",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["last_opened_edition_id"],
            ["book_editions.id"],
            name="fk_user_book_preferences_last_opened_edition_id_book_editions",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["preferred_edition_id"],
            ["book_editions.id"],
            name="fk_user_book_preferences_preferred_edition_id_book_editions",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_user_book_preferences_user_id_users",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("user_id", "book_id", name="pk_user_book_preferences"),
    )


def downgrade() -> None:
    op.drop_table("user_book_preferences")
    op.drop_index("ix_books_owner_user_id", table_name="books")
    op.drop_constraint("fk_books_owner_user_id_users", "books", type_="foreignkey")
    op.drop_column("books", "owner_user_id")
    op.drop_index("ix_auth_audit_events_type_created", table_name="auth_audit_events")
    op.drop_index("ix_auth_audit_events_subject_user_id", table_name="auth_audit_events")
    op.drop_index("ix_auth_audit_events_actor_user_id", table_name="auth_audit_events")
    op.drop_table("auth_audit_events")
    op.drop_table("login_throttles")
    op.drop_index("ix_refresh_tokens_session_id", table_name="refresh_tokens")
    op.drop_table("refresh_tokens")
    op.drop_index("ix_auth_sessions_user_device", table_name="auth_sessions")
    op.drop_index("ix_auth_sessions_device_id", table_name="auth_sessions")
    op.drop_index("ix_auth_sessions_user_id", table_name="auth_sessions")
    op.drop_table("auth_sessions")
    op.drop_index("ix_devices_user_id", table_name="devices")
    op.drop_table("devices")
    op.drop_table("users")
    bind = op.get_bind()
    device_platform.drop(bind, checkfirst=True)
    user_status.drop(bind, checkfirst=True)
    user_role.drop(bind, checkfirst=True)
