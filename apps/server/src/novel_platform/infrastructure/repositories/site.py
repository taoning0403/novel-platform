from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from novel_platform.infrastructure.database.models import SiteSettingsModel


class SiteRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, *, for_update: bool = False) -> SiteSettingsModel:
        statement = select(SiteSettingsModel).where(SiteSettingsModel.id == 1)
        if for_update:
            statement = statement.with_for_update()
        settings = (await self.session.scalars(statement)).one_or_none()
        if settings is None:
            raise RuntimeError("site settings singleton is missing")
        return settings
