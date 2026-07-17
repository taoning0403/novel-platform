from fastapi import APIRouter

from novel_platform.api.dependencies.auth import CurrentAdmin
from novel_platform.api.dependencies.database import DatabaseSession
from novel_platform.api.schemas import (
    PublicSiteSettingsResponse,
    SiteSettingsPatch,
    SiteSettingsResponse,
)
from novel_platform.api.serializers import public_site_settings_response, site_settings_response
from novel_platform.application.site.service import SiteSettingsService

router = APIRouter(tags=["site-settings"])


@router.get("/site", response_model=PublicSiteSettingsResponse)
async def public_site_settings(session: DatabaseSession) -> PublicSiteSettingsResponse:
    return public_site_settings_response(await SiteSettingsService(session).get())


@router.get("/admin/site", response_model=SiteSettingsResponse)
async def admin_site_settings(
    session: DatabaseSession, _admin: CurrentAdmin
) -> SiteSettingsResponse:
    return site_settings_response(await SiteSettingsService(session).get())


@router.patch("/admin/site", response_model=SiteSettingsResponse)
async def update_site_settings(
    payload: SiteSettingsPatch,
    session: DatabaseSession,
    admin: CurrentAdmin,
) -> SiteSettingsResponse:
    row = await SiteSettingsService(session).update(admin, payload.model_dump(exclude_unset=True))
    return site_settings_response(row)
