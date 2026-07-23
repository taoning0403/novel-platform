from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from novel_platform.domain.auth.capabilities import (
    CredentialCapability,
    sorted_capabilities,
    validate_credential_capabilities,
)
from novel_platform.domain.auth.models import (
    AccessCredentialStatus,
    DevicePlatform,
    UserStatus,
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
)
from novel_platform.domain.reader.models import ReaderFontFamily, ReaderTheme, ReadingStatus
from novel_platform.domain.translations.models import (
    TranslationCleanupStatus,
    TranslationRunStatus,
)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


def validate_capability_list(
    values: list[CredentialCapability],
) -> list[CredentialCapability]:
    try:
        capabilities = validate_credential_capabilities(values)
    except ValueError as error:
        raise ValueError(str(error)) from error
    return sorted_capabilities(capabilities)


class ErrorDetail(BaseModel):
    code: str
    message: str
    details: dict[str, Any]


class ErrorResponse(BaseModel):
    error: ErrorDetail


class ContributorSummary(BaseModel):
    display_name: str


class ResourcePermissionsResponse(BaseModel):
    can_edit: bool
    can_delete: bool
    can_upload_edition: bool
    can_translate: bool


class BookResponse(ResourcePermissionsResponse):
    id: UUID
    canonical_title: str
    canonical_author: str | None
    description: str | None
    metadata: dict[str, Any]
    contributor: ContributorSummary
    cover_url: str | None
    cover_thumbnail_url: str | None
    created_at: datetime
    updated_at: datetime


class BookListItem(ResourcePermissionsResponse):
    id: UUID
    canonical_title: str
    canonical_author: str | None
    description: str | None
    contributor: ContributorSummary
    edition_count: int
    languages: list[str]
    file_formats: list[FileFormat]
    preferred_edition_id: UUID | None
    preferred_edition_title: str | None
    cover_thumbnail_url: str | None
    series_id: UUID | None = None
    series_name: str | None = None
    series_position: int | None = None
    reading_status: ReadingStatus = ReadingStatus.NOT_STARTED
    reading_progress: float = 0
    last_read_at: datetime | None = None
    continue_edition_id: UUID | None = None
    continue_edition_title: str | None = None
    continue_url: str | None = None
    created_at: datetime
    updated_at: datetime


class BookPatch(StrictModel):
    canonical_title: str | None = None
    canonical_author: str | None = None
    description: str | None = None
    metadata: dict[str, Any] | None = None

    @model_validator(mode="after")
    def validate_patch(self) -> "BookPatch":
        if not self.model_fields_set:
            raise ValueError("at least one field is required")
        if "canonical_title" in self.model_fields_set:
            if self.canonical_title is None or not self.canonical_title.strip():
                raise ValueError("canonical_title cannot be blank")
            self.canonical_title = self.canonical_title.strip()
        if "metadata" in self.model_fields_set and self.metadata is None:
            raise ValueError("metadata cannot be null")
        return self


class SeriesCreate(StrictModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=5000)

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be blank")
        return value


class SeriesPatch(StrictModel):
    name: str | None = Field(default=None, max_length=200)
    description: str | None = Field(default=None, max_length=5000)

    @model_validator(mode="after")
    def validate_patch(self) -> "SeriesPatch":
        if not self.model_fields_set:
            raise ValueError("at least one field is required")
        if "name" in self.model_fields_set:
            if self.name is None or not self.name.strip():
                raise ValueError("name cannot be blank")
            self.name = self.name.strip()
        return self


class SeriesResponse(BaseModel):
    id: UUID
    name: str
    description: str | None
    book_count: int
    created_at: datetime
    updated_at: datetime


class SeriesDetailResponse(SeriesResponse):
    books: list[BookListItem]


class EditionPatch(StrictModel):
    title: str | None = None
    status: EditionStatus | None = None
    source_edition_id: UUID | None = None
    supersedes_edition_id: UUID | None = None
    metadata: dict[str, Any] | None = None

    @field_validator("title")
    @classmethod
    def strip_patch_title(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("must not be blank")
        return value

    @model_validator(mode="after")
    def reject_null_non_nullable_fields(self) -> "EditionPatch":
        for field_name in ("title", "status", "metadata"):
            if field_name in self.model_fields_set and getattr(self, field_name) is None:
                raise ValueError(f"{field_name} cannot be null")
        return self


class EditionResponse(ResourcePermissionsResponse):
    id: UUID
    book_id: UUID
    title: str
    language: str
    content_role: ContentRole
    translation_origin: TranslationOrigin | None
    creation_method: CreationMethod
    source_edition_id: UUID | None
    supersedes_edition_id: UUID | None
    status: EditionStatus
    revision: int
    metadata: dict[str, Any]
    contributor: ContributorSummary
    current_file: "EditionFileResponse | None"
    reader_available: bool
    reading_status: ReadingStatus
    reading_progress: float
    last_read_at: datetime | None
    created_at: datetime
    updated_at: datetime


class BookDetailResponse(BookResponse):
    edition_count: int
    editions: list[EditionResponse]


class EditionFileResponse(BaseModel):
    revision: int
    file_format: FileFormat
    original_filename: str
    media_type: str
    size_bytes: int
    text_encoding: str | None
    content_item_count: int | None
    uploaded_at: datetime
    download_url: str | None


class ImportResponse(BaseModel):
    id: UUID
    status: ImportStatus
    operation: ImportOperation
    original_filename: str
    file_format: FileFormat | None
    size_bytes: int | None
    target_book_id: UUID | None
    target_edition_id: UUID | None
    text_encoding: str | None
    content_item_count: int | None
    metadata_preview: dict[str, Any]
    warnings: list[str]
    cover_available: bool
    cover_preview_url: str | None
    error_code: str | None
    error_message: str | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None


class ImportCommitRequest(StrictModel):
    series_id: UUID | None = None
    canonical_title: str | None = None
    canonical_author: str | None = None
    description: str | None = None
    book_metadata: dict[str, Any] = Field(default_factory=dict)
    edition_title: str | None = None
    language: str | None = None
    content_role: ContentRole | None = None
    translation_origin: TranslationOrigin | None = None
    source_edition_id: UUID | None = None
    supersedes_edition_id: UUID | None = None
    edition_status: EditionStatus = EditionStatus.READY
    edition_metadata: dict[str, Any] = Field(default_factory=dict)
    set_preferred: bool = False
    use_extracted_cover: bool | None = None


class ImportCommitResponse(BaseModel):
    upload: ImportResponse
    book: BookResponse
    edition: EditionResponse


class ReaderSettingsResponse(BaseModel):
    font_size: int
    line_height: float
    content_width: int
    font_family: ReaderFontFamily
    theme: ReaderTheme
    updated_at: datetime


class ReaderSettingsPatch(StrictModel):
    font_size: int | None = Field(default=None, ge=12, le=36)
    line_height: float | None = Field(default=None, ge=1.2, le=2.8)
    content_width: int | None = Field(default=None, ge=480, le=1200)
    font_family: ReaderFontFamily | None = None
    theme: ReaderTheme | None = None

    @model_validator(mode="after")
    def validate_patch(self) -> "ReaderSettingsPatch":
        if not self.model_fields_set:
            raise ValueError("at least one field is required")
        if any(getattr(self, field) is None for field in self.model_fields_set):
            raise ValueError("reader settings cannot be null")
        return self


class ReadingProgressResponse(BaseModel):
    edition_id: UUID
    status: ReadingStatus
    section_id: str | None
    block_id: str | None
    section_progress: float
    overall_progress: float
    edition_file_revision: int | None
    version: int
    last_read_at: datetime | None


class ReadingProgressUpdate(StrictModel):
    expected_version: int = Field(ge=0)
    section_id: str = Field(min_length=1, max_length=100)
    block_id: str | None = Field(default=None, max_length=100)
    section_progress: float = Field(ge=0, le=1)
    overall_progress: float = Field(ge=0, le=1)
    edition_file_revision: int = Field(ge=1)
    status: ReadingStatus | None = None


class ReaderSectionDescriptor(BaseModel):
    id: str
    index: int
    title: str


class ReaderTocEntry(BaseModel):
    title: str
    section_id: str


class ReaderPublicationResponse(BaseModel):
    file_format: FileFormat
    file_revision: int
    sections: list[ReaderSectionDescriptor]
    toc: list[ReaderTocEntry]


class ReaderSectionResponse(ReaderSectionDescriptor):
    html: str
    resource_ids: list[str]


class ReaderEditionOption(BaseModel):
    id: UUID
    book_id: UUID
    title: str
    language: str
    content_role: ContentRole
    translation_origin: TranslationOrigin | None
    file_format: FileFormat
    reading_status: ReadingStatus
    reading_progress: float
    last_read_at: datetime | None


class ReaderOpenResponse(BaseModel):
    book: BookResponse
    edition: ReaderEditionOption
    available_editions: list[ReaderEditionOption]
    publication: ReaderPublicationResponse
    progress: ReadingProgressResponse
    settings: ReaderSettingsResponse


class RecentReadingResponse(BaseModel):
    book_id: UUID
    book_title: str
    book_cover_thumbnail_url: str | None
    edition_id: UUID
    edition_title: str
    edition_language: str
    file_format: FileFormat
    series_id: UUID | None
    series_name: str | None
    status: ReadingStatus
    progress: float
    last_read_at: datetime
    continue_url: str


class HealthResponse(BaseModel):
    status: str


class TranslationServiceStatusResponse(BaseModel):
    enabled: bool
    available: bool
    version: str | None
    pipeline_key: str
    pipeline_version: str | None
    provider_id: str
    provider_name: str | None
    provider_model: str | None
    provider_offline: bool
    idempotency_required: bool | None
    error_code: str | None
    error_message: str | None


class TranslationRunCreate(StrictModel):
    target_language: str = Field(min_length=1, max_length=100)
    edition_title: str = Field(min_length=1, max_length=500)
    client_request_id: UUID
    supersedes_edition_id: UUID | None = None

    @field_validator("target_language", "edition_title")
    @classmethod
    def strip_translation_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be blank")
        return value


class TranslationRunResponse(BaseModel):
    id: UUID
    book_id: UUID
    book_title: str
    source_edition_id: UUID
    source_edition_title: str
    source_revision: int
    source_sha256: str
    source_format: FileFormat
    target_language: str
    edition_title: str
    supersedes_edition_id: UUID | None
    configuration: dict[str, Any]
    creator: ContributorSummary
    status: TranslationRunStatus
    progress: float
    generated_edition_id: UUID | None
    generated_edition_title: str | None
    remote_project_id: str | None
    remote_job_id: str | None
    remote_artifact_id: str | None
    remote_request_id: str | None
    remote_status: str | None
    error_code: str | None
    error_message: str | None
    error_details: dict[str, Any]
    retry_count: int
    cleanup_status: TranslationCleanupStatus
    cleanup_error: str | None
    available_actions: list[Literal["pause", "resume", "cancel", "retry", "sync", "cleanup"]]
    can_preview_draft: bool
    can_publish: bool
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    last_synced_at: datetime | None


class BookPreferencePatch(StrictModel):
    preferred_edition_id: UUID | None = None
    last_opened_edition_id: UUID | None = None


class BookPreferenceResponse(BaseModel):
    preferred_edition_id: UUID | None
    last_opened_edition_id: UUID | None


class UserResponse(BaseModel):
    id: UUID
    display_name: str
    role: Literal["admin", "reader"]
    capabilities: list[CredentialCapability]
    status: UserStatus
    last_login_at: datetime | None
    created_at: datetime
    updated_at: datetime


class LoginDevice(StrictModel):
    client_instance_id: UUID
    name: str = Field(min_length=1, max_length=100)
    platform: DevicePlatform
    app_version: str | None = Field(default=None, max_length=100)


class CredentialLoginRequest(StrictModel):
    credential: str = Field(min_length=1, max_length=1024, json_schema_extra={"format": "password"})
    refresh_token_delivery: Literal["cookie", "body"] = "cookie"
    device: LoginDevice


class RefreshRequest(StrictModel):
    refresh_token: str = Field(min_length=1, max_length=1024)


class LoginDeviceResponse(BaseModel):
    id: UUID
    name: str
    platform: DevicePlatform


class LoginSessionResponse(BaseModel):
    id: UUID
    created_at: datetime
    expires_at: datetime
    recovery_mode: bool


class TokenResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int
    refresh_token: str | None = None
    user: UserResponse
    device: LoginDeviceResponse
    session: LoginSessionResponse


class MeResponse(BaseModel):
    user: UserResponse
    device: LoginDeviceResponse
    session: LoginSessionResponse


class SessionResponse(BaseModel):
    id: UUID
    device_id: UUID
    device_name: str
    platform: DevicePlatform
    created_at: datetime
    last_seen_at: datetime
    expires_at: datetime
    is_current: bool
    revoked: bool
    recovery_mode: bool


class RevokeOthersResponse(BaseModel):
    revoked_count: int


class DeviceResponse(BaseModel):
    id: UUID
    name: str
    platform: DevicePlatform
    app_version: str | None
    first_seen_at: datetime
    last_seen_at: datetime
    revoked_at: datetime | None
    is_current: bool
    active_session_count: int


class DevicePatch(StrictModel):
    name: str = Field(min_length=1, max_length=200)


class ProfilePatch(StrictModel):
    display_name: str = Field(min_length=1, max_length=200)


class PublicSiteSettingsResponse(BaseModel):
    site_name: str
    purpose_statement: str
    privacy_statement: str
    icp_registration_number: str | None
    icp_registration_url: str | None


class SiteSettingsResponse(PublicSiteSettingsResponse):
    default_reader_max_devices: int
    audit_retention_days: int
    admin_locked: bool
    migration_completed: bool
    updated_at: datetime


class SiteSettingsPatch(StrictModel):
    site_name: str | None = Field(default=None, min_length=1, max_length=200)
    purpose_statement: str | None = Field(default=None, min_length=1, max_length=5000)
    privacy_statement: str | None = Field(default=None, min_length=1, max_length=5000)
    icp_registration_number: str | None = Field(default=None, max_length=100)
    icp_registration_url: str | None = Field(default=None, max_length=500)
    default_reader_max_devices: int | None = Field(default=None, ge=1, le=100)
    audit_retention_days: int | None = Field(default=None, ge=1, le=3650)

    @model_validator(mode="after")
    def validate_patch(self) -> "SiteSettingsPatch":
        if not self.model_fields_set:
            raise ValueError("at least one field is required")
        nullable = {"icp_registration_number", "icp_registration_url"}
        for field_name in self.model_fields_set - nullable:
            if getattr(self, field_name) is None:
                raise ValueError(f"{field_name} cannot be null")
        if self.icp_registration_url and not self.icp_registration_url.startswith(
            ("https://", "http://")
        ):
            raise ValueError("icp_registration_url must be HTTP or HTTPS")
        return self


class ReaderCredentialResponse(BaseModel):
    id: UUID
    hint: str
    lifecycle_status: AccessCredentialStatus
    effective_status: Literal["active", "suspended", "revoked", "expired"]
    expires_at: datetime
    allow_new_devices: bool
    max_devices: int
    capabilities: list[CredentialCapability]
    active_device_count: int
    last_used_at: datetime | None
    suspended_at: datetime | None
    revoked_at: datetime | None
    reissued_at: datetime | None
    created_at: datetime


class ReaderResponse(BaseModel):
    id: UUID
    display_name: str
    admin_note: str | None
    status: UserStatus
    credential: ReaderCredentialResponse | None
    created_at: datetime
    updated_at: datetime


class ReaderCreate(StrictModel):
    display_name: str = Field(min_length=1, max_length=100)
    admin_note: str | None = Field(default=None, max_length=5000)
    expires_at: datetime
    max_devices: int | None = Field(default=None, ge=1, le=100)
    allow_new_devices: bool = True
    capabilities: list[CredentialCapability]

    _validate_capabilities = field_validator("capabilities")(validate_capability_list)

    @field_validator("expires_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("expires_at must include a timezone")
        return value


class ReaderPatch(StrictModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=100)
    admin_note: str | None = Field(default=None, max_length=5000)
    expires_at: datetime | None = None
    max_devices: int | None = Field(default=None, ge=1, le=100)
    allow_new_devices: bool | None = None

    @field_validator("expires_at")
    @classmethod
    def require_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("expires_at must include a timezone")
        return value

    @model_validator(mode="after")
    def require_change(self) -> "ReaderPatch":
        if not self.model_fields_set:
            raise ValueError("at least one field is required")
        for field_name in self.model_fields_set - {"admin_note"}:
            if getattr(self, field_name) is None:
                raise ValueError(f"{field_name} cannot be null")
        return self


class CredentialReissueRequest(StrictModel):
    expires_at: datetime
    max_devices: int | None = Field(default=None, ge=1, le=100)
    allow_new_devices: bool = True
    capabilities: list[CredentialCapability]

    _validate_capabilities = field_validator("capabilities")(validate_capability_list)

    @field_validator("expires_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("expires_at must include a timezone")
        return value


class IssuedReaderCredentialResponse(BaseModel):
    reader: ReaderResponse
    access_credential: str


class WebAuthnOptionsResponse(BaseModel):
    challenge_id: UUID
    options: dict[str, Any]


class PasskeyRegistrationRequest(StrictModel):
    challenge_id: UUID
    name: str = Field(min_length=1, max_length=100)
    credential: dict[str, Any]


class PasskeyAuthenticationRequest(StrictModel):
    challenge_id: UUID
    credential: dict[str, Any]
    refresh_token_delivery: Literal["cookie", "body"] = "cookie"
    device: LoginDevice


class PasskeyResponse(BaseModel):
    id: UUID
    name: str
    device_type: str | None
    backed_up: bool
    last_used_at: datetime | None
    revoked_at: datetime | None
    created_at: datetime


class PasskeyRegistrationResponse(BaseModel):
    passkey: PasskeyResponse
    authentication: TokenResponse | None = None


class PasskeyPatch(StrictModel):
    name: str = Field(min_length=1, max_length=100)


class SecurityAuditEventResponse(BaseModel):
    id: UUID
    event_type: str
    outcome: str
    actor_user_id: UUID | None
    subject_user_id: UUID | None
    session_id: UUID | None
    device_id: UUID | None
    access_credential_id: UUID | None
    passkey_id: UUID | None
    client_ip: str | None
    user_agent_summary: str | None
    metadata: dict[str, Any]
    created_at: datetime
