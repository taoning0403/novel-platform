from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from novel_platform.api.schemas import (
    BookDetailResponse,
    BookListItem,
    BookResponse,
    ContributorSummary,
    DeviceResponse,
    EditionFileResponse,
    EditionResponse,
    ImportResponse,
    LoginDeviceResponse,
    LoginSessionResponse,
    MeResponse,
    PasskeyResponse,
    PublicSiteSettingsResponse,
    ReaderCredentialResponse,
    ReaderResponse,
    SecurityAuditEventResponse,
    SeriesResponse,
    SessionResponse,
    SiteSettingsResponse,
    TokenResponse,
    UserResponse,
)
from novel_platform.application.auth.context import AuthContext, TokenResult
from novel_platform.application.library.policy import ResourcePermissions
from novel_platform.domain.auth.capabilities import CredentialCapability, sorted_capabilities
from novel_platform.domain.auth.models import AccessCredentialStatus, UserRole
from novel_platform.domain.library.models import FileFormat
from novel_platform.domain.reader.models import ReadingStatus
from novel_platform.infrastructure.database.models import (
    AdminPasskeyModel,
    AuthAuditEventModel,
    AuthSessionModel,
    BookEditionModel,
    BookModel,
    BookSeriesModel,
    DeviceModel,
    LibraryImportModel,
    ReaderAccessCredentialModel,
    ReadingProgressModel,
    SiteSettingsModel,
    UserModel,
)
from novel_platform.infrastructure.repositories.library import (
    BookLibrarySummary,
    EditionFileRecord,
)


def user_response(
    user: UserModel,
    capabilities: frozenset[CredentialCapability],
) -> UserResponse:
    return UserResponse(
        id=user.id,
        display_name=user.display_name,
        role="admin" if user.role == UserRole.ADMIN else "reader",
        capabilities=sorted_capabilities(capabilities),
        status=user.status,
        last_login_at=user.last_login_at,
        created_at=user.created_at,
        updated_at=user.updated_at,
    )


def login_device_response(device: DeviceModel) -> LoginDeviceResponse:
    return LoginDeviceResponse(id=device.id, name=device.name, platform=device.platform)


def login_session_response(auth_session: AuthSessionModel) -> LoginSessionResponse:
    return LoginSessionResponse(
        id=auth_session.id,
        created_at=auth_session.created_at,
        expires_at=auth_session.expires_at,
        recovery_mode=auth_session.recovery_mode,
    )


def me_response(context: AuthContext) -> MeResponse:
    return MeResponse(
        user=user_response(context.user, context.capabilities),
        device=login_device_response(context.device),
        session=login_session_response(context.session),
    )


def token_response(result: TokenResult, *, include_refresh: bool) -> TokenResponse:
    context = result.context
    return TokenResponse(
        access_token=result.access_token,
        expires_in=result.expires_in,
        refresh_token=result.refresh_token if include_refresh else None,
        user=user_response(context.user, context.capabilities),
        device=login_device_response(context.device),
        session=login_session_response(context.session),
    )


def session_response(
    auth_session: AuthSessionModel, device: DeviceModel, *, current_session_id: UUID
) -> SessionResponse:
    return SessionResponse(
        id=auth_session.id,
        device_id=device.id,
        device_name=device.name,
        platform=device.platform,
        created_at=auth_session.created_at,
        last_seen_at=auth_session.last_seen_at,
        expires_at=auth_session.expires_at,
        is_current=auth_session.id == current_session_id,
        revoked=auth_session.revoked_at is not None,
        recovery_mode=auth_session.recovery_mode,
    )


def public_site_settings_response(settings: SiteSettingsModel) -> PublicSiteSettingsResponse:
    return PublicSiteSettingsResponse(
        site_name=settings.site_name,
        purpose_statement=settings.purpose_statement,
        privacy_statement=settings.privacy_statement,
        icp_registration_number=settings.icp_registration_number,
        icp_registration_url=(
            settings.icp_registration_url if settings.icp_registration_number else None
        ),
    )


def site_settings_response(settings: SiteSettingsModel) -> SiteSettingsResponse:
    return SiteSettingsResponse(
        **public_site_settings_response(settings).model_dump(),
        default_reader_max_devices=settings.default_reader_max_devices,
        audit_retention_days=settings.audit_retention_days,
        admin_locked=settings.admin_locked_at is not None,
        migration_completed=settings.migration_completed_at is not None,
        updated_at=settings.updated_at,
    )


def reader_credential_response(
    credential: ReaderAccessCredentialModel,
    active_device_count: int,
    capabilities: frozenset[CredentialCapability],
    *,
    now: datetime | None = None,
) -> ReaderCredentialResponse:
    current = now or datetime.now(UTC)
    effective_status: Literal["active", "suspended", "revoked", "expired"]
    if credential.status == AccessCredentialStatus.REVOKED:
        effective_status = "revoked"
    elif credential.status == AccessCredentialStatus.SUSPENDED:
        effective_status = "suspended"
    elif credential.expires_at <= current:
        effective_status = "expired"
    else:
        effective_status = "active"
    return ReaderCredentialResponse(
        id=credential.id,
        hint=credential.credential_hint,
        lifecycle_status=credential.status,
        effective_status=effective_status,
        expires_at=credential.expires_at,
        allow_new_devices=credential.allow_new_devices,
        max_devices=credential.max_devices,
        capabilities=sorted_capabilities(capabilities),
        active_device_count=active_device_count,
        last_used_at=credential.last_used_at,
        suspended_at=credential.suspended_at,
        revoked_at=credential.revoked_at,
        reissued_at=credential.reissued_at,
        created_at=credential.created_at,
    )


def reader_response(
    user: UserModel,
    credential: ReaderAccessCredentialModel | None,
    active_device_count: int,
    capabilities: frozenset[CredentialCapability],
) -> ReaderResponse:
    return ReaderResponse(
        id=user.id,
        display_name=user.display_name,
        admin_note=user.admin_note,
        status=user.status,
        credential=(
            reader_credential_response(credential, active_device_count, capabilities)
            if credential is not None
            else None
        ),
        created_at=user.created_at,
        updated_at=user.updated_at,
    )


def passkey_response(passkey: AdminPasskeyModel) -> PasskeyResponse:
    return PasskeyResponse(
        id=passkey.id,
        name=passkey.name,
        device_type=passkey.device_type,
        backed_up=passkey.backed_up,
        last_used_at=passkey.last_used_at,
        revoked_at=passkey.revoked_at,
        created_at=passkey.created_at,
    )


def audit_event_response(event: AuthAuditEventModel) -> SecurityAuditEventResponse:
    return SecurityAuditEventResponse(
        id=event.id,
        event_type=event.event_type,
        outcome=event.outcome,
        actor_user_id=event.actor_user_id,
        subject_user_id=event.subject_user_id,
        session_id=event.session_id,
        device_id=event.device_id,
        access_credential_id=event.access_credential_id,
        passkey_id=event.passkey_id,
        client_ip=event.client_ip,
        user_agent_summary=event.user_agent_summary,
        metadata=event.event_metadata,
        created_at=event.created_at,
    )


def device_response(
    device: DeviceModel, active_session_count: int, *, current_device_id: UUID | None
) -> DeviceResponse:
    return DeviceResponse(
        id=device.id,
        name=device.name,
        platform=device.platform,
        app_version=device.app_version,
        first_seen_at=device.first_seen_at,
        last_seen_at=device.last_seen_at,
        revoked_at=device.revoked_at,
        is_current=device.id == current_device_id,
        active_session_count=active_session_count,
    )


def permission_fields(permissions: ResourcePermissions) -> dict[str, bool]:
    return {
        "can_edit": permissions.can_edit,
        "can_delete": permissions.can_delete,
        "can_upload_edition": permissions.can_upload_edition,
        "can_translate": permissions.can_translate,
    }


def book_response(
    book: BookModel,
    *,
    contributor_display_name: str,
    permissions: ResourcePermissions,
) -> BookResponse:
    return BookResponse(
        **permission_fields(permissions),
        id=book.id,
        canonical_title=book.canonical_title,
        canonical_author=book.canonical_author,
        description=book.description,
        metadata=book.extra_metadata,
        contributor=ContributorSummary(display_name=contributor_display_name),
        cover_url=f"/api/v1/books/{book.id}/cover" if book.cover_file_id else None,
        cover_thumbnail_url=(
            f"/api/v1/books/{book.id}/cover?thumbnail=true"
            if book.cover_thumbnail_file_id
            else None
        ),
        created_at=book.created_at,
        updated_at=book.updated_at,
    )


def book_list_item(
    book: BookModel,
    edition_count: int,
    summary: BookLibrarySummary | None = None,
    *,
    contributor_display_name: str,
    permissions: ResourcePermissions,
    series_id: UUID | None = None,
    series_name: str | None = None,
    series_position: int | None = None,
) -> BookListItem:
    return BookListItem(
        **permission_fields(permissions),
        id=book.id,
        canonical_title=book.canonical_title,
        canonical_author=book.canonical_author,
        description=book.description,
        contributor=ContributorSummary(display_name=contributor_display_name),
        edition_count=edition_count,
        languages=summary.languages if summary else [],
        file_formats=(
            [FileFormat(file_format) for file_format in summary.file_formats] if summary else []
        ),
        preferred_edition_id=summary.preferred_edition_id if summary else None,
        preferred_edition_title=summary.preferred_edition_title if summary else None,
        cover_thumbnail_url=(
            f"/api/v1/books/{book.id}/cover?thumbnail=true"
            if book.cover_thumbnail_file_id
            else None
        ),
        series_id=series_id,
        series_name=series_name,
        series_position=series_position,
        reading_status=(
            ReadingStatus(summary.reading_status)
            if summary and summary.reading_status
            else ReadingStatus.NOT_STARTED
        ),
        reading_progress=summary.reading_progress if summary else 0,
        last_read_at=summary.last_read_at if summary else None,
        continue_edition_id=summary.continue_edition_id if summary else None,
        continue_edition_title=summary.continue_edition_title if summary else None,
        continue_url=(
            f"/read/{summary.continue_edition_id}"
            if summary and summary.continue_edition_id
            else None
        ),
        created_at=book.created_at,
        updated_at=book.updated_at,
    )


def series_response(series: BookSeriesModel, book_count: int) -> SeriesResponse:
    return SeriesResponse(
        id=series.id,
        name=series.name,
        description=series.description,
        book_count=book_count,
        created_at=series.created_at,
        updated_at=series.updated_at,
    )


def edition_response(
    edition: BookEditionModel,
    file_record: EditionFileRecord | None = None,
    progress: ReadingProgressModel | None = None,
    *,
    contributor_display_name: str,
    permissions: ResourcePermissions,
    include_download: bool = True,
) -> EditionResponse:
    return EditionResponse(
        **permission_fields(permissions),
        id=edition.id,
        book_id=edition.book_id,
        title=edition.title,
        language=edition.language,
        content_role=edition.content_role,
        translation_origin=edition.translation_origin,
        creation_method=edition.creation_method,
        source_edition_id=edition.source_edition_id,
        supersedes_edition_id=edition.supersedes_edition_id,
        status=edition.status,
        revision=edition.revision,
        metadata=edition.extra_metadata,
        contributor=ContributorSummary(display_name=contributor_display_name),
        current_file=(
            edition_file_response(file_record, include_download=include_download)
            if file_record
            else None
        ),
        reader_available=bool(
            file_record
            and file_record.stored_file.file_format in {FileFormat.EPUB, FileFormat.TXT}
            and (
                file_record.stored_file.file_format is FileFormat.EPUB
                or file_record.normalized_file is not None
            )
        ),
        reading_status=progress.status if progress else ReadingStatus.NOT_STARTED,
        reading_progress=progress.overall_progress if progress else 0,
        last_read_at=progress.last_read_at if progress else None,
        created_at=edition.created_at,
        updated_at=edition.updated_at,
    )


def book_detail_response(
    book: BookModel,
    editions: list[BookEditionModel],
    files: dict[UUID, EditionFileRecord] | None = None,
    progresses: dict[UUID, ReadingProgressModel] | None = None,
    *,
    contributor_display_name: str,
    permissions: ResourcePermissions,
    edition_contributors: dict[UUID, str],
    edition_permissions: dict[UUID, ResourcePermissions],
    include_download: bool = True,
) -> BookDetailResponse:
    return BookDetailResponse(
        **permission_fields(permissions),
        id=book.id,
        canonical_title=book.canonical_title,
        canonical_author=book.canonical_author,
        description=book.description,
        metadata=book.extra_metadata,
        contributor=ContributorSummary(display_name=contributor_display_name),
        cover_url=f"/api/v1/books/{book.id}/cover" if book.cover_file_id else None,
        cover_thumbnail_url=(
            f"/api/v1/books/{book.id}/cover?thumbnail=true"
            if book.cover_thumbnail_file_id
            else None
        ),
        created_at=book.created_at,
        updated_at=book.updated_at,
        edition_count=len(editions),
        editions=[
            edition_response(
                edition,
                (files or {}).get(edition.id),
                (progresses or {}).get(edition.id),
                contributor_display_name=edition_contributors[edition.id],
                permissions=edition_permissions[edition.id],
                include_download=include_download,
            )
            for edition in editions
        ],
    )


def edition_file_response(
    record: EditionFileRecord, *, include_download: bool = True
) -> EditionFileResponse:
    return EditionFileResponse(
        revision=record.edition_file.revision,
        file_format=record.stored_file.file_format,
        original_filename=record.stored_file.original_filename,
        media_type=record.stored_file.media_type,
        size_bytes=record.stored_file.size_bytes,
        text_encoding=record.edition_file.text_encoding,
        content_item_count=record.edition_file.content_item_count,
        uploaded_at=record.edition_file.created_at,
        download_url=(
            f"/api/v1/editions/{record.edition_file.edition_id}/file" if include_download else None
        ),
    )


def import_response(library_import: LibraryImportModel) -> ImportResponse:
    cover_available = bool(library_import.cover_temporary_storage_key)
    return ImportResponse(
        id=library_import.id,
        status=library_import.status,
        operation=library_import.operation,
        original_filename=library_import.original_filename,
        file_format=library_import.file_format,
        size_bytes=library_import.size_bytes,
        target_book_id=library_import.target_book_id,
        target_edition_id=library_import.target_edition_id,
        text_encoding=library_import.text_encoding,
        content_item_count=library_import.content_item_count,
        metadata_preview=library_import.metadata_preview,
        warnings=library_import.warnings,
        cover_available=cover_available,
        cover_preview_url=(
            f"/api/v1/imports/{library_import.id}/cover" if cover_available else None
        ),
        error_code=library_import.error_code,
        error_message=library_import.error_message,
        created_at=library_import.created_at,
        started_at=library_import.started_at,
        completed_at=library_import.completed_at,
    )
