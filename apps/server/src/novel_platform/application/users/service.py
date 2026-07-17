from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from novel_platform.application.auth.context import AuthContext
from novel_platform.domain.auth.rules import normalize_display_name
from novel_platform.infrastructure.database.models import UserModel


class UserService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def update_me(self, actor: AuthContext, display_name: str) -> UserModel:
        actor.user.display_name = normalize_display_name(display_name)
        actor.user.updated_at = datetime.now(UTC)
        await self.session.commit()
        return actor.user
