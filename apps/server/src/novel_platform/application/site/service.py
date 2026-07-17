from datetime import UTC, datetime
from http import HTTPStatus
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from novel_platform.application.auth.context import AuthContext
from novel_platform.application.errors import ApplicationError
from novel_platform.infrastructure.database.models import SiteSettingsModel
from novel_platform.infrastructure.repositories.auth import AuthRepository
from novel_platform.infrastructure.repositories.site import SiteRepository


class SiteSettingsService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.site = SiteRepository(session)
        self.auth = AuthRepository(session)

    async def get(self) -> SiteSettingsModel:
        return await self.site.get()

    async def update(self, actor: AuthContext, changes: dict[str, Any]) -> SiteSettingsModel:
        allowed = {
            "site_name",
            "purpose_statement",
            "privacy_statement",
            "icp_registration_number",
            "icp_registration_url",
            "default_reader_max_devices",
            "audit_retention_days",
        }
        if not changes or set(changes) - allowed:
            raise ApplicationError(
                "validation_error",
                "至少需要提供一个有效的站点设置字段。",
                status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
            )
        site = await self.site.get(for_update=True)
        for field_name in ("site_name", "purpose_statement", "privacy_statement"):
            if field_name in changes:
                value = str(changes[field_name]).strip()
                if not value:
                    raise ApplicationError("validation_error", "站点公开文案不能为空。")
                setattr(site, field_name, value)
        if "icp_registration_number" in changes:
            value = changes["icp_registration_number"]
            site.icp_registration_number = str(value).strip() if value else None
        if "icp_registration_url" in changes:
            value = changes["icp_registration_url"]
            site.icp_registration_url = str(value).strip() if value else None
        if not site.icp_registration_number:
            site.icp_registration_url = None
        for field_name in ("default_reader_max_devices", "audit_retention_days"):
            if field_name in changes:
                numeric_value = int(changes[field_name])
                if numeric_value < 1:
                    raise ApplicationError("validation_error", "数值必须是正整数。")
                setattr(site, field_name, numeric_value)
        site.updated_at = datetime.now(UTC)
        self.auth.audit(
            "site_settings_updated",
            "success",
            actor_user_id=actor.user.id,
            subject_user_id=actor.user.id,
            metadata={"fields": sorted(changes)},
        )
        await self.session.commit()
        return site
