from uuid import UUID

from fastapi import APIRouter, Response, status

from novel_platform.api.dependencies.auth import CurrentAdmin
from novel_platform.api.dependencies.database import DatabaseSession
from novel_platform.api.schemas import (
    CredentialReissueRequest,
    DeviceResponse,
    IssuedReaderCredentialResponse,
    ReaderCreate,
    ReaderPatch,
    ReaderResponse,
    RevokeOthersResponse,
    SecurityAuditEventResponse,
)
from novel_platform.api.serializers import (
    audit_event_response,
    device_response,
    reader_response,
)
from novel_platform.application.readers.service import ReaderManagementService
from novel_platform.config import get_settings

router = APIRouter(prefix="/admin/readers", tags=["reader-administration"])


@router.get("", response_model=list[ReaderResponse])
async def list_readers(session: DatabaseSession, _admin: CurrentAdmin) -> list[ReaderResponse]:
    rows = await ReaderManagementService(session, get_settings()).list_readers()
    return [reader_response(*row) for row in rows]


@router.post("", response_model=IssuedReaderCredentialResponse, status_code=status.HTTP_201_CREATED)
async def create_reader(
    payload: ReaderCreate,
    response: Response,
    session: DatabaseSession,
    admin: CurrentAdmin,
) -> IssuedReaderCredentialResponse:
    issued = await ReaderManagementService(session, get_settings()).create_reader(
        admin,
        display_name=payload.display_name,
        admin_note=payload.admin_note,
        expires_at=payload.expires_at,
        max_devices=payload.max_devices,
        allow_new_devices=payload.allow_new_devices,
        capabilities=payload.capabilities,
    )
    response.headers["Cache-Control"] = "no-store"
    return IssuedReaderCredentialResponse(
        reader=reader_response(issued.user, issued.credential, 0, issued.capabilities),
        access_credential=issued.raw_credential,
    )


@router.get("/{reader_id}", response_model=ReaderResponse)
async def get_reader(
    reader_id: UUID, session: DatabaseSession, _admin: CurrentAdmin
) -> ReaderResponse:
    return reader_response(
        *await ReaderManagementService(session, get_settings()).get_reader(reader_id)
    )


@router.patch("/{reader_id}", response_model=ReaderResponse)
async def update_reader(
    reader_id: UUID,
    payload: ReaderPatch,
    session: DatabaseSession,
    admin: CurrentAdmin,
) -> ReaderResponse:
    row = await ReaderManagementService(session, get_settings()).update_reader(
        admin,
        reader_id,
        display_name=payload.display_name,
        admin_note=payload.admin_note,
        admin_note_set="admin_note" in payload.model_fields_set,
        expires_at=payload.expires_at,
        max_devices=payload.max_devices,
        allow_new_devices=payload.allow_new_devices,
    )
    return reader_response(*row)


@router.post("/{reader_id}/credential/suspend", status_code=status.HTTP_204_NO_CONTENT)
async def suspend_credential(
    reader_id: UUID, session: DatabaseSession, admin: CurrentAdmin
) -> None:
    await ReaderManagementService(session, get_settings()).suspend(admin, reader_id)


@router.post("/{reader_id}/credential/resume", status_code=status.HTTP_204_NO_CONTENT)
async def resume_credential(reader_id: UUID, session: DatabaseSession, admin: CurrentAdmin) -> None:
    await ReaderManagementService(session, get_settings()).resume(admin, reader_id)


@router.post("/{reader_id}/credential/revoke", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_credential(reader_id: UUID, session: DatabaseSession, admin: CurrentAdmin) -> None:
    await ReaderManagementService(session, get_settings()).revoke(admin, reader_id)


@router.post("/{reader_id}/credential/reissue", response_model=IssuedReaderCredentialResponse)
async def reissue_credential(
    reader_id: UUID,
    payload: CredentialReissueRequest,
    response: Response,
    session: DatabaseSession,
    admin: CurrentAdmin,
) -> IssuedReaderCredentialResponse:
    issued = await ReaderManagementService(session, get_settings()).reissue(
        admin,
        reader_id,
        expires_at=payload.expires_at,
        max_devices=payload.max_devices,
        allow_new_devices=payload.allow_new_devices,
        capabilities=payload.capabilities,
    )
    response.headers["Cache-Control"] = "no-store"
    return IssuedReaderCredentialResponse(
        reader=reader_response(issued.user, issued.credential, 0, issued.capabilities),
        access_credential=issued.raw_credential,
    )


@router.post("/{reader_id}/sessions/revoke-all", response_model=RevokeOthersResponse)
async def revoke_reader_sessions(
    reader_id: UUID, session: DatabaseSession, admin: CurrentAdmin
) -> RevokeOthersResponse:
    count = await ReaderManagementService(session, get_settings()).revoke_all_sessions(
        admin, reader_id
    )
    return RevokeOthersResponse(revoked_count=count)


@router.get("/{reader_id}/devices", response_model=list[DeviceResponse])
async def list_reader_devices(
    reader_id: UUID, session: DatabaseSession, _admin: CurrentAdmin
) -> list[DeviceResponse]:
    rows = await ReaderManagementService(session, get_settings()).list_devices(reader_id)
    return [device_response(device, count, current_device_id=None) for device, count in rows]


@router.post("/{reader_id}/devices/{device_id}/revoke", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_reader_device(
    reader_id: UUID,
    device_id: UUID,
    session: DatabaseSession,
    admin: CurrentAdmin,
) -> None:
    await ReaderManagementService(session, get_settings()).revoke_device(
        admin, reader_id, device_id
    )


@router.get("/{reader_id}/audit", response_model=list[SecurityAuditEventResponse])
async def reader_audit(
    reader_id: UUID, session: DatabaseSession, _admin: CurrentAdmin
) -> list[SecurityAuditEventResponse]:
    rows = await ReaderManagementService(session, get_settings()).audit_events(reader_id)
    return [audit_event_response(row) for row in rows]
