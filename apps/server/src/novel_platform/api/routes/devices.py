from uuid import UUID

from fastapi import APIRouter, Response, status

from novel_platform.api.dependencies.auth import CurrentAuth
from novel_platform.api.dependencies.database import DatabaseSession
from novel_platform.api.routes.auth import clear_device_cookie, clear_refresh_cookie
from novel_platform.api.schemas import DevicePatch, DeviceResponse
from novel_platform.api.serializers import device_response
from novel_platform.application.auth.service import AuthService
from novel_platform.config import get_settings

router = APIRouter(prefix="/devices", tags=["devices"])


@router.get("", response_model=list[DeviceResponse])
async def list_devices(session: DatabaseSession, current: CurrentAuth) -> list[DeviceResponse]:
    rows = await AuthService(session, get_settings()).list_devices(current)
    return [
        device_response(device, count, current_device_id=current.device.id)
        for device, count in rows
    ]


@router.patch("/{device_id}", response_model=DeviceResponse)
async def rename_device(
    device_id: UUID,
    payload: DevicePatch,
    session: DatabaseSession,
    current: CurrentAuth,
) -> DeviceResponse:
    service = AuthService(session, get_settings())
    device = await service.rename_device(current, device_id, payload.name)
    rows = await service.list_devices(current)
    active_count = next(count for row, count in rows if row.id == device.id)
    return device_response(device, active_count, current_device_id=current.device.id)


@router.post("/{device_id}/revoke", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_device(
    device_id: UUID,
    response: Response,
    session: DatabaseSession,
    current: CurrentAuth,
) -> None:
    settings = get_settings()
    revoked_current = await AuthService(session, settings).revoke_device(current, device_id)
    if revoked_current:
        clear_refresh_cookie(response, settings)
        clear_device_cookie(response, settings)
