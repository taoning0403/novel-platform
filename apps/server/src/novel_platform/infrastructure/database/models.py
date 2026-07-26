from datetime import datetime
from enum import Enum as PyEnum
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from novel_platform.domain.auth.capabilities import CredentialCapability
from novel_platform.domain.auth.models import (
    AccessCredentialStatus,
    AdminRecoveryPurpose,
    DevicePlatform,
    UserRole,
    UserStatus,
    WebAuthnChallengePurpose,
)
from novel_platform.domain.editions.models import (
    ContentRole,
    CreationMethod,
    EditionStatus,
    TranslationOrigin,
)
from novel_platform.domain.library.models import (
    FileFormat,
    ImportOperation,
    ImportStatus,
    StoredFilePurpose,
)
from novel_platform.domain.reader.models import ReaderFontFamily, ReaderTheme, ReadingStatus
from novel_platform.domain.translations.models import (
    TranslationCleanupStatus,
    TranslationRunStatus,
)
from novel_platform.infrastructure.database.base import Base


def enum_values(enum_class: type[PyEnum]) -> list[str]:
    return [str(item.value) for item in enum_class]


class UserModel(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("length(btrim(username)) > 0", name="username_not_blank"),
        CheckConstraint("length(btrim(display_name)) > 0", name="display_name_not_blank"),
    )

    id: Mapped[UUID] = mapped_column(
        primary_key=True, default=uuid4, server_default=text("gen_random_uuid()")
    )
    username: Mapped[str] = mapped_column(String(64), nullable=False)
    normalized_username: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    display_name: Mapped[str] = mapped_column(String(100), nullable=False)
    admin_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole, name="user_role", values_callable=enum_values, validate_strings=True),
        nullable=False,
    )
    status: Mapped[UserStatus] = mapped_column(
        Enum(UserStatus, name="user_status", values_callable=enum_values, validate_strings=True),
        nullable=False,
    )
    password_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    password_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class SiteSettingsModel(Base):
    __tablename__ = "site_settings"
    __table_args__ = (
        CheckConstraint("id = 1", name="singleton"),
        CheckConstraint("length(btrim(site_name)) > 0", name="site_name_not_blank"),
        CheckConstraint("length(btrim(purpose_statement)) > 0", name="purpose_not_blank"),
        CheckConstraint("length(btrim(privacy_statement)) > 0", name="privacy_not_blank"),
        CheckConstraint("default_reader_max_devices >= 1", name="default_devices_positive"),
        CheckConstraint("audit_retention_days >= 1", name="retention_positive"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1, server_default="1")
    site_name: Mapped[str] = mapped_column(String(200), nullable=False)
    purpose_statement: Mapped[str] = mapped_column(Text, nullable=False)
    privacy_statement: Mapped[str] = mapped_column(Text, nullable=False)
    icp_registration_number: Mapped[str | None] = mapped_column(String(100), nullable=True)
    icp_registration_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    default_reader_max_devices: Mapped[int] = mapped_column(
        Integer, nullable=False, default=3, server_default="3"
    )
    audit_retention_days: Mapped[int] = mapped_column(
        Integer, nullable=False, default=90, server_default="90"
    )
    library_owner_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=True, unique=True
    )
    admin_locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    migration_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ReaderAccessCredentialModel(Base):
    __tablename__ = "reader_access_credentials"
    __table_args__ = (
        CheckConstraint("length(token_hash) = 64", name="token_hash_length"),
        CheckConstraint("length(btrim(credential_hint)) > 0", name="hint_not_blank"),
        CheckConstraint("max_devices >= 1", name="max_devices_positive"),
        Index(
            "uq_reader_access_credentials_current",
            "user_id",
            unique=True,
            postgresql_where=text("status <> 'revoked'"),
        ),
        Index("ix_reader_access_credentials_user_created", "user_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(
        primary_key=True, default=uuid4, server_default=text("gen_random_uuid()")
    )
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    credential_hint: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[AccessCredentialStatus] = mapped_column(
        Enum(
            AccessCredentialStatus,
            name="access_credential_status",
            values_callable=enum_values,
            validate_strings=True,
        ),
        nullable=False,
        default=AccessCredentialStatus.ACTIVE,
        server_default=AccessCredentialStatus.ACTIVE.value,
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    allow_new_devices: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    max_devices: Mapped[int] = mapped_column(Integer, nullable=False)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    suspended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reissued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by_admin_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    updated_by_admin_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    replaced_by_credential_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("reader_access_credentials.id", ondelete="RESTRICT"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ReaderCredentialCapabilityModel(Base):
    __tablename__ = "reader_credential_capabilities"
    __table_args__ = (
        CheckConstraint(
            "capability IN ('library.read', 'library.upload', 'translation.use')",
            name="known_capability",
        ),
        Index("ix_reader_credential_capabilities_capability", "capability"),
    )

    credential_id: Mapped[UUID] = mapped_column(
        ForeignKey("reader_access_credentials.id", ondelete="CASCADE"), primary_key=True
    )
    capability: Mapped[str] = mapped_column(String(64), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    @property
    def value(self) -> CredentialCapability:
        return CredentialCapability(self.capability)


class ProviderCredentialVersionModel(Base):
    __tablename__ = "provider_credential_versions"
    __table_args__ = (
        CheckConstraint(
            "provider IN ('openai_compatible', 'deepseek', 'kimi', 'custom')",
            name="provider_known",
        ),
        CheckConstraint(
            "(provider = 'custom' AND provider_name IS NOT NULL "
            "AND length(btrim(provider_name)) > 0) "
            "OR (provider <> 'custom' AND provider_name IS NULL)",
            name="provider_name_matches_provider",
        ),
        CheckConstraint(
            "length(btrim(base_url)) > 0",
            name="base_url_not_blank",
        ),
        CheckConstraint(
            "length(btrim(model)) > 0",
            name="model_not_blank",
        ),
        CheckConstraint("version >= 1", name="version_positive"),
        CheckConstraint("octet_length(nonce) = 12", name="nonce_length"),
        CheckConstraint("octet_length(ciphertext) >= 17", name="ciphertext_has_tag"),
        CheckConstraint(
            "algorithm IN ('aes-256-gcm-v1', 'aes-256-gcm-v2')",
            name="algorithm_supported",
        ),
        CheckConstraint(
            "retired_at IS NULL OR retired_at >= created_at",
            name="retired_after_creation",
        ),
        CheckConstraint(
            "revoked_at IS NULL OR revoked_at >= created_at",
            name="revoked_after_creation",
        ),
        UniqueConstraint("user_id", "version", name="user_version"),
        Index(
            "uq_provider_credential_versions_current",
            "user_id",
            unique=True,
            postgresql_where=text("retired_at IS NULL AND revoked_at IS NULL"),
        ),
        Index(
            "ix_provider_credential_versions_user_created",
            "user_id",
            "created_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        primary_key=True, default=uuid4, server_default=text("gen_random_uuid()")
    )
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    provider: Mapped[str] = mapped_column(
        String(32), nullable=False, default="openai_compatible", server_default="openai_compatible"
    )
    provider_name: Mapped[str | None] = mapped_column(String(120))
    base_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    model: Mapped[str] = mapped_column(String(120), nullable=False)
    thinking_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    algorithm: Mapped[str] = mapped_column(
        String(32), nullable=False, default="aes-256-gcm-v2", server_default="aes-256-gcm-v2"
    )
    nonce: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    ciphertext: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ProviderUsageRecordModel(Base):
    __tablename__ = "provider_usage_records"
    __table_args__ = (
        CheckConstraint("prompt_tokens >= 0", name="prompt_tokens_nonnegative"),
        CheckConstraint("completion_tokens >= 0", name="completion_tokens_nonnegative"),
        CheckConstraint("total_tokens >= 0", name="total_tokens_nonnegative"),
        CheckConstraint(
            "total_tokens >= prompt_tokens AND total_tokens >= completion_tokens",
            name="total_tokens_consistent",
        ),
        CheckConstraint("length(btrim(model)) > 0", name="model_not_blank"),
        Index(
            "ix_provider_usage_records_credential_created",
            "provider_credential_version_id",
            "created_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        primary_key=True, default=uuid4, server_default=text("gen_random_uuid()")
    )
    provider_credential_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("provider_credential_versions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    model: Mapped[str] = mapped_column(String(120), nullable=False)
    prompt_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    completion_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    total_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    remote_job_id: Mapped[str | None] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class AdminRecoveryCredentialModel(Base):
    __tablename__ = "admin_recovery_credentials"
    __table_args__ = (
        CheckConstraint("length(token_hash) = 64", name="token_hash_length"),
        CheckConstraint("length(btrim(credential_hint)) > 0", name="hint_not_blank"),
        Index("ix_admin_recovery_credentials_user_created", "user_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(
        primary_key=True, default=uuid4, server_default=text("gen_random_uuid()")
    )
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    credential_hint: Mapped[str] = mapped_column(String(20), nullable=False)
    purpose: Mapped[AdminRecoveryPurpose] = mapped_column(
        Enum(
            AdminRecoveryPurpose,
            name="admin_recovery_purpose",
            values_callable=enum_values,
            validate_strings=True,
        ),
        nullable=False,
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class AdminPasskeyModel(Base):
    __tablename__ = "admin_passkeys"
    __table_args__ = (
        CheckConstraint("length(btrim(name)) > 0", name="name_not_blank"),
        Index("ix_admin_passkeys_user_created", "user_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(
        primary_key=True, default=uuid4, server_default=text("gen_random_uuid()")
    )
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    credential_id: Mapped[bytes] = mapped_column(LargeBinary, nullable=False, unique=True)
    public_key: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    sign_count: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    transports: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    device_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    backed_up: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class WebAuthnChallengeModel(Base):
    __tablename__ = "webauthn_challenges"
    __table_args__ = (Index("ix_webauthn_challenges_expires", "expires_at"),)

    id: Mapped[UUID] = mapped_column(
        primary_key=True, default=uuid4, server_default=text("gen_random_uuid()")
    )
    challenge: Mapped[bytes] = mapped_column(LargeBinary, nullable=False, unique=True)
    purpose: Mapped[WebAuthnChallengePurpose] = mapped_column(
        Enum(
            WebAuthnChallengePurpose,
            name="webauthn_challenge_purpose",
            values_callable=enum_values,
            validate_strings=True,
        ),
        nullable=False,
    )
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    expected_origin: Mapped[str] = mapped_column(String(500), nullable=False)
    rp_id: Mapped[str] = mapped_column(String(255), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class StoredFileModel(Base):
    __tablename__ = "stored_files"
    __table_args__ = (
        CheckConstraint("size_bytes >= 0", name="size_bytes_nonnegative"),
        CheckConstraint(
            "storage_key ~ '^[0-9a-f]{64}$'",
            name="storage_key_lower_hex",
        ),
        CheckConstraint(
            "sha256 ~ '^[0-9a-f]{64}$'",
            name="sha256_lower_hex",
        ),
        CheckConstraint(
            "length(btrim(original_filename)) > 0",
            name="original_filename_not_blank",
        ),
        CheckConstraint(
            "(purpose = 'edition_source' AND file_format IN ('epub', 'txt')) OR "
            "(purpose = 'normalized_text' AND file_format = 'txt') OR "
            "(purpose = 'book_cover' AND file_format IN ('jpeg', 'png', 'webp', 'gif')) OR "
            "(purpose = 'cover_thumbnail' AND file_format = 'jpeg')",
            name="purpose_format_consistent",
        ),
        Index("ix_stored_files_owner_sha256", "owner_user_id", "sha256"),
    )

    id: Mapped[UUID] = mapped_column(
        primary_key=True, default=uuid4, server_default=text("gen_random_uuid()")
    )
    owner_user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    created_by_user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    storage_key: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    media_type: Mapped[str] = mapped_column(String(100), nullable=False)
    file_format: Mapped[FileFormat] = mapped_column(
        Enum(FileFormat, name="file_format", values_callable=enum_values, validate_strings=True),
        nullable=False,
    )
    purpose: Mapped[StoredFilePurpose] = mapped_column(
        Enum(
            StoredFilePurpose,
            name="stored_file_purpose",
            values_callable=enum_values,
            validate_strings=True,
        ),
        nullable=False,
    )
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class BookModel(Base):
    __tablename__ = "books"
    __table_args__ = (
        CheckConstraint("length(btrim(canonical_title)) > 0", name="title_not_blank"),
    )

    id: Mapped[UUID] = mapped_column(
        primary_key=True, default=uuid4, server_default=text("gen_random_uuid()")
    )
    owner_user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    created_by_user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    canonical_title: Mapped[str] = mapped_column(String, nullable=False)
    canonical_author: Mapped[str | None] = mapped_column(String, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    cover_file_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("stored_files.id", ondelete="RESTRICT"), nullable=True
    )
    cover_thumbnail_file_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("stored_files.id", ondelete="RESTRICT"), nullable=True
    )
    extra_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class BookEditionModel(Base):
    __tablename__ = "book_editions"
    __table_args__ = (
        CheckConstraint("length(btrim(title)) > 0", name="title_not_blank"),
        CheckConstraint("length(btrim(language)) > 0", name="language_not_blank"),
        CheckConstraint("revision >= 1", name="revision_at_least_one"),
        CheckConstraint(
            "source_edition_id IS NULL OR source_edition_id <> id",
            name="source_not_self",
        ),
        CheckConstraint(
            "supersedes_edition_id IS NULL OR supersedes_edition_id <> id",
            name="supersedes_not_self",
        ),
        CheckConstraint(
            "(content_role = 'source' AND translation_origin IS NULL "
            "AND source_edition_id IS NULL) OR "
            "(content_role = 'translation' AND translation_origin IS NOT NULL)",
            name="role_origin_and_source_consistent",
        ),
        Index("ix_book_editions_book_created", "book_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(
        primary_key=True, default=uuid4, server_default=text("gen_random_uuid()")
    )
    book_id: Mapped[UUID] = mapped_column(
        ForeignKey("books.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    created_by_user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String, nullable=False)
    language: Mapped[str] = mapped_column(String, nullable=False)
    content_role: Mapped[ContentRole] = mapped_column(
        Enum(
            ContentRole,
            name="content_role",
            values_callable=enum_values,
            validate_strings=True,
        ),
        nullable=False,
    )
    translation_origin: Mapped[TranslationOrigin | None] = mapped_column(
        Enum(
            TranslationOrigin,
            name="translation_origin",
            values_callable=enum_values,
            validate_strings=True,
        ),
        nullable=True,
    )
    creation_method: Mapped[CreationMethod] = mapped_column(
        Enum(
            CreationMethod,
            name="creation_method",
            values_callable=enum_values,
            validate_strings=True,
        ),
        nullable=False,
    )
    source_edition_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("book_editions.id", ondelete="RESTRICT"), nullable=True
    )
    supersedes_edition_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("book_editions.id", ondelete="RESTRICT"), nullable=True
    )
    status: Mapped[EditionStatus] = mapped_column(
        Enum(
            EditionStatus,
            name="edition_status",
            values_callable=enum_values,
            validate_strings=True,
        ),
        nullable=False,
        default=EditionStatus.DRAFT,
        server_default=EditionStatus.DRAFT.value,
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    extra_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class EditionFileModel(Base):
    __tablename__ = "edition_files"
    __table_args__ = (
        CheckConstraint("revision >= 1", name="revision_at_least_one"),
        CheckConstraint(
            "content_item_count IS NULL OR content_item_count >= 0",
            name="content_item_count_nonnegative",
        ),
        CheckConstraint(
            "normalized_stored_file_id IS NULL OR normalized_stored_file_id <> stored_file_id",
            name="normalized_file_is_distinct",
        ),
        UniqueConstraint("edition_id", "revision", name="edition_revision"),
        Index(
            "uq_edition_files_current",
            "edition_id",
            unique=True,
            postgresql_where=text("is_current"),
        ),
    )

    id: Mapped[UUID] = mapped_column(
        primary_key=True, default=uuid4, server_default=text("gen_random_uuid()")
    )
    edition_id: Mapped[UUID] = mapped_column(
        ForeignKey("book_editions.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    stored_file_id: Mapped[UUID] = mapped_column(
        ForeignKey("stored_files.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    normalized_stored_file_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("stored_files.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    text_encoding: Mapped[str | None] = mapped_column(String(40), nullable=True)
    content_item_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    extracted_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class LibraryImportModel(Base):
    __tablename__ = "library_imports"
    __table_args__ = (
        CheckConstraint(
            "length(btrim(original_filename)) > 0",
            name="original_filename_not_blank",
        ),
        CheckConstraint("size_bytes IS NULL OR size_bytes >= 0", name="size_bytes_nonnegative"),
        CheckConstraint(
            "sha256 IS NULL OR sha256 ~ '^[0-9a-f]{64}$'",
            name="sha256_lower_hex",
        ),
        CheckConstraint(
            "content_item_count IS NULL OR content_item_count >= 0",
            name="content_item_count_nonnegative",
        ),
        CheckConstraint(
            "(temporary_storage_key IS NULL OR "
            "temporary_storage_key ~ '^[0-9a-f]{64}$') AND "
            "(normalized_temporary_storage_key IS NULL OR "
            "normalized_temporary_storage_key ~ '^[0-9a-f]{64}$') AND "
            "(cover_temporary_storage_key IS NULL OR "
            "cover_temporary_storage_key ~ '^[0-9a-f]{64}$') AND "
            "(cover_thumbnail_temporary_storage_key IS NULL OR "
            "cover_thumbnail_temporary_storage_key ~ '^[0-9a-f]{64}$')",
            name="temporary_keys_lower_hex",
        ),
        Index("ix_library_imports_owner_created", "owner_user_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(
        primary_key=True, default=uuid4, server_default=text("gen_random_uuid()")
    )
    owner_user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    requested_by_user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    status: Mapped[ImportStatus] = mapped_column(
        Enum(
            ImportStatus,
            name="library_import_status",
            values_callable=enum_values,
            validate_strings=True,
        ),
        nullable=False,
    )
    operation: Mapped[ImportOperation] = mapped_column(
        Enum(
            ImportOperation,
            name="library_import_operation",
            values_callable=enum_values,
            validate_strings=True,
        ),
        nullable=False,
    )
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    submitted_media_type: Mapped[str | None] = mapped_column(String(200), nullable=True)
    file_format: Mapped[FileFormat | None] = mapped_column(
        Enum(FileFormat, name="file_format", values_callable=enum_values, create_constraint=False),
        nullable=True,
    )
    size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    target_book_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("books.id", ondelete="SET NULL"), nullable=True, index=True
    )
    target_edition_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("book_editions.id", ondelete="SET NULL"), nullable=True, index=True
    )
    stored_file_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("stored_files.id", ondelete="SET NULL"), nullable=True
    )
    temporary_storage_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    normalized_temporary_storage_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    cover_temporary_storage_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    cover_thumbnail_temporary_storage_key: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    cover_filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    cover_media_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    cover_file_format: Mapped[FileFormat | None] = mapped_column(
        Enum(FileFormat, name="file_format", values_callable=enum_values, create_constraint=False),
        nullable=True,
    )
    text_encoding: Mapped[str | None] = mapped_column(String(40), nullable=True)
    content_item_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    metadata_preview: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    warnings: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class EditionTranslationRunModel(Base):
    __tablename__ = "edition_translation_runs"
    __table_args__ = (
        CheckConstraint("source_revision >= 1", name="source_revision_positive"),
        CheckConstraint("source_sha256 ~ '^[0-9a-f]{64}$'", name="source_sha256_lower_hex"),
        CheckConstraint("source_format = 'txt'", name="source_format_txt"),
        CheckConstraint("length(btrim(target_language)) > 0", name="target_language_not_blank"),
        CheckConstraint("length(btrim(edition_title)) > 0", name="edition_title_not_blank"),
        CheckConstraint(
            "configuration_fingerprint ~ '^[0-9a-f]{64}$'",
            name="configuration_fingerprint_lower_hex",
        ),
        CheckConstraint("progress >= 0 AND progress <= 1", name="progress_range"),
        CheckConstraint("retry_count >= 0", name="retry_count_nonnegative"),
        CheckConstraint(
            "status IN ('preparing', 'queued', 'running', 'paused', 'cancelling', "
            "'cancelled', 'partially_succeeded', 'failed', 'ingesting', 'succeeded', "
            "'attention_required')",
            name="known_status",
        ),
        CheckConstraint(
            "cleanup_status IN ('not_required', 'pending', 'succeeded', 'failed')",
            name="known_cleanup_status",
        ),
        UniqueConstraint(
            "created_by_user_id",
            "client_request_id",
            name="actor_client_request",
        ),
        Index(
            "uq_translation_runs_active_equivalent",
            "source_edition_file_id",
            "target_language",
            "configuration_fingerprint",
            unique=True,
            postgresql_where=text(
                "status IN ('preparing', 'queued', 'running', 'paused', 'cancelling', "
                "'ingesting', 'attention_required')"
            ),
        ),
        Index(
            "uq_translation_runs_remote_project",
            "remote_project_id",
            unique=True,
            postgresql_where=text("remote_project_id IS NOT NULL"),
        ),
        Index(
            "uq_translation_runs_remote_job",
            "remote_job_id",
            unique=True,
            postgresql_where=text("remote_job_id IS NOT NULL"),
        ),
        Index(
            "uq_translation_runs_remote_artifact",
            "remote_artifact_id",
            unique=True,
            postgresql_where=text("remote_artifact_id IS NOT NULL"),
        ),
        Index(
            "uq_translation_runs_generated_edition",
            "generated_edition_id",
            unique=True,
            postgresql_where=text("generated_edition_id IS NOT NULL"),
        ),
        Index("ix_translation_runs_owner_created", "library_owner_user_id", "created_at"),
        Index("ix_translation_runs_actor_created", "created_by_user_id", "created_at"),
        Index("ix_translation_runs_book_created", "book_id", "created_at"),
        Index("ix_translation_runs_source_edition", "source_edition_id"),
        Index(
            "ix_edition_translation_runs_provider_credential_version_id",
            "provider_credential_version_id",
        ),
        Index(
            "uq_translation_runs_credential_bootstrap",
            "provider_credential_version_id",
            unique=True,
            postgresql_where=text("remote_job_id IS NULL AND status = 'preparing'"),
        ),
    )

    id: Mapped[UUID] = mapped_column(
        primary_key=True, default=uuid4, server_default=text("gen_random_uuid()")
    )
    library_owner_user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_by_user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    provider_credential_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("provider_credential_versions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    book_id: Mapped[UUID] = mapped_column(
        ForeignKey("books.id", ondelete="RESTRICT"), nullable=False
    )
    source_edition_id: Mapped[UUID] = mapped_column(
        ForeignKey("book_editions.id", ondelete="RESTRICT"), nullable=False
    )
    source_edition_file_id: Mapped[UUID] = mapped_column(
        ForeignKey("edition_files.id", ondelete="RESTRICT"), nullable=False
    )
    source_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    source_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    source_format: Mapped[FileFormat] = mapped_column(
        Enum(FileFormat, name="file_format", values_callable=enum_values, create_constraint=False),
        nullable=False,
    )
    target_language: Mapped[str] = mapped_column(String(100), nullable=False)
    edition_title: Mapped[str] = mapped_column(String, nullable=False)
    supersedes_edition_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("book_editions.id", ondelete="RESTRICT"), nullable=True
    )
    configuration_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    configuration_snapshot: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    client_request_id: Mapped[UUID] = mapped_column(nullable=False)
    remote_project_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    remote_job_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    remote_artifact_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    remote_request_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    remote_status: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[TranslationRunStatus] = mapped_column(
        Enum(
            TranslationRunStatus,
            name="translation_run_status",
            values_callable=enum_values,
            native_enum=False,
            create_constraint=False,
        ),
        nullable=False,
        default=TranslationRunStatus.PREPARING,
        server_default=TranslationRunStatus.PREPARING.value,
    )
    progress: Mapped[float] = mapped_column(Float, nullable=False, default=0, server_default="0")
    generated_edition_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("book_editions.id", ondelete="SET NULL"), nullable=True
    )
    error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_details: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    cleanup_status: Mapped[TranslationCleanupStatus] = mapped_column(
        Enum(
            TranslationCleanupStatus,
            name="translation_cleanup_status",
            values_callable=enum_values,
            native_enum=False,
            create_constraint=False,
        ),
        nullable=False,
        default=TranslationCleanupStatus.NOT_REQUIRED,
        server_default=TranslationCleanupStatus.NOT_REQUIRED.value,
    )
    cleanup_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class BookSeriesModel(Base):
    __tablename__ = "book_series"
    __table_args__ = (
        CheckConstraint("length(btrim(name)) > 0", name="name_not_blank"),
        Index("ix_book_series_owner_updated", "owner_user_id", "updated_at"),
    )

    id: Mapped[UUID] = mapped_column(
        primary_key=True, default=uuid4, server_default=text("gen_random_uuid()")
    )
    owner_user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class SeriesMembershipModel(Base):
    __tablename__ = "series_memberships"
    __table_args__ = (
        CheckConstraint("position >= 1", name="position_positive"),
        UniqueConstraint("series_id", "position", name="series_position"),
    )

    series_id: Mapped[UUID] = mapped_column(
        ForeignKey("book_series.id", ondelete="CASCADE"), nullable=False, index=True
    )
    book_id: Mapped[UUID] = mapped_column(
        ForeignKey("books.id", ondelete="CASCADE"), primary_key=True
    )
    position: Mapped[int] = mapped_column(BigInteger, nullable=False)
    added_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ReaderSettingsModel(Base):
    __tablename__ = "reader_settings"
    __table_args__ = (
        CheckConstraint("font_size BETWEEN 12 AND 36", name="font_size_range"),
        CheckConstraint("line_height BETWEEN 1.2 AND 2.8", name="line_height_range"),
        CheckConstraint("content_width BETWEEN 480 AND 1200", name="content_width_range"),
    )

    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), primary_key=True
    )
    font_size: Mapped[int] = mapped_column(Integer, nullable=False, default=18, server_default="18")
    line_height: Mapped[float] = mapped_column(
        Float, nullable=False, default=1.8, server_default="1.8"
    )
    content_width: Mapped[int] = mapped_column(
        Integer, nullable=False, default=760, server_default="760"
    )
    font_family: Mapped[ReaderFontFamily] = mapped_column(
        Enum(
            ReaderFontFamily,
            name="reader_font_family",
            values_callable=enum_values,
            validate_strings=True,
        ),
        nullable=False,
        default=ReaderFontFamily.SERIF,
        server_default=ReaderFontFamily.SERIF.value,
    )
    theme: Mapped[ReaderTheme] = mapped_column(
        Enum(ReaderTheme, name="reader_theme", values_callable=enum_values, validate_strings=True),
        nullable=False,
        default=ReaderTheme.LIGHT,
        server_default=ReaderTheme.LIGHT.value,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ReadingProgressModel(Base):
    __tablename__ = "reading_progresses"
    __table_args__ = (
        CheckConstraint("section_progress BETWEEN 0 AND 1", name="section_progress_range"),
        CheckConstraint("overall_progress BETWEEN 0 AND 1", name="overall_progress_range"),
        CheckConstraint(
            "edition_file_revision IS NULL OR edition_file_revision >= 1",
            name="file_revision_positive",
        ),
        CheckConstraint("version >= 1", name="version_positive"),
        Index("ix_reading_progresses_user_last_read", "user_id", "last_read_at"),
    )

    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), primary_key=True
    )
    edition_id: Mapped[UUID] = mapped_column(
        ForeignKey("book_editions.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    status: Mapped[ReadingStatus] = mapped_column(
        Enum(
            ReadingStatus,
            name="reading_status",
            values_callable=enum_values,
            validate_strings=True,
        ),
        nullable=False,
        default=ReadingStatus.NOT_STARTED,
        server_default=ReadingStatus.NOT_STARTED.value,
    )
    section_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    block_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    section_progress: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.0, server_default="0"
    )
    overall_progress: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.0, server_default="0"
    )
    edition_file_revision: Mapped[int | None] = mapped_column(Integer, nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    updated_device_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("devices.id", ondelete="SET NULL"), nullable=True
    )
    last_read_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class DeviceModel(Base):
    __tablename__ = "devices"
    __table_args__ = (
        CheckConstraint("length(btrim(name)) > 0", name="name_not_blank"),
        CheckConstraint(
            "device_secret_hash IS NULL OR length(device_secret_hash) = 64",
            name="device_secret_hash_length",
        ),
        Index("ix_devices_user_last_seen", "user_id", "last_seen_at"),
    )

    id: Mapped[UUID] = mapped_column(
        primary_key=True, default=uuid4, server_default=text("gen_random_uuid()")
    )
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    access_credential_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("reader_access_credentials.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    client_instance_id: Mapped[UUID] = mapped_column(nullable=False)
    device_secret_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, unique=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    platform: Mapped[DevicePlatform] = mapped_column(
        Enum(
            DevicePlatform,
            name="device_platform",
            values_callable=enum_values,
            validate_strings=True,
        ),
        nullable=False,
    )
    app_version: Mapped[str | None] = mapped_column(String(100))
    first_authorized_ip: Mapped[str | None] = mapped_column(String(64))
    last_used_ip: Mapped[str | None] = mapped_column(String(64))
    user_agent_summary: Mapped[str | None] = mapped_column(String(255))
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class AuthSessionModel(Base):
    __tablename__ = "auth_sessions"
    __table_args__ = (Index("ix_auth_sessions_user_device", "user_id", "device_id"),)

    id: Mapped[UUID] = mapped_column(
        primary_key=True, default=uuid4, server_default=text("gen_random_uuid()")
    )
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    device_id: Mapped[UUID] = mapped_column(
        ForeignKey("devices.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    access_credential_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("reader_access_credentials.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    passkey_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("admin_passkeys.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    recovery_credential_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("admin_recovery_credentials.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    recovery_mode: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoke_reason: Mapped[str | None] = mapped_column(String(100))


class RefreshTokenModel(Base):
    __tablename__ = "refresh_tokens"

    id: Mapped[UUID] = mapped_column(
        primary_key=True, default=uuid4, server_default=text("gen_random_uuid()")
    )
    session_id: Mapped[UUID] = mapped_column(
        ForeignKey("auth_sessions.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    issued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    replaced_by_token_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("refresh_tokens.id", ondelete="RESTRICT")
    )


class LoginThrottleModel(Base):
    __tablename__ = "login_throttles"
    __table_args__ = (CheckConstraint("failure_count >= 0", name="failure_count_nonnegative"),)

    key_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    failure_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    window_started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    blocked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AuthAuditEventModel(Base):
    __tablename__ = "auth_audit_events"
    __table_args__ = (Index("ix_auth_audit_events_type_created", "event_type", "created_at"),)

    id: Mapped[UUID] = mapped_column(
        primary_key=True, default=uuid4, server_default=text("gen_random_uuid()")
    )
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    outcome: Mapped[str] = mapped_column(String(32), nullable=False)
    actor_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), index=True
    )
    subject_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), index=True
    )
    session_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("auth_sessions.id", ondelete="RESTRICT")
    )
    device_id: Mapped[UUID | None] = mapped_column(ForeignKey("devices.id", ondelete="RESTRICT"))
    access_credential_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("reader_access_credentials.id", ondelete="RESTRICT"), nullable=True
    )
    passkey_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("admin_passkeys.id", ondelete="RESTRICT"), nullable=True
    )
    client_ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent_summary: Mapped[str | None] = mapped_column(String(255), nullable=True)
    event_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class UserBookPreferenceModel(Base):
    __tablename__ = "user_book_preferences"

    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), primary_key=True
    )
    book_id: Mapped[UUID] = mapped_column(
        ForeignKey("books.id", ondelete="RESTRICT"), primary_key=True
    )
    preferred_edition_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("book_editions.id", ondelete="RESTRICT")
    )
    last_opened_edition_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("book_editions.id", ondelete="RESTRICT")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
