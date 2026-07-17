from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from novel_platform.application.auth.context import AuthContext
from novel_platform.infrastructure.database.models import AuthAuditEventModel
from novel_platform.infrastructure.repositories.auth import AuthRepository
from novel_platform.infrastructure.repositories.site import SiteRepository


class AuditService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.auth = AuthRepository(session)
        self.site = SiteRepository(session)

    async def list_events(
        self,
        *,
        event_type: str | None,
        subject_user_id: UUID | None,
        outcome: str | None,
        created_from: datetime | None,
        created_to: datetime | None,
        limit: int,
        offset: int,
    ) -> list[AuthAuditEventModel]:
        statement = select(AuthAuditEventModel)
        if event_type:
            statement = statement.where(AuthAuditEventModel.event_type == event_type)
        if subject_user_id:
            statement = statement.where(AuthAuditEventModel.subject_user_id == subject_user_id)
        if outcome:
            statement = statement.where(AuthAuditEventModel.outcome == outcome)
        if created_from:
            statement = statement.where(AuthAuditEventModel.created_at >= created_from)
        if created_to:
            statement = statement.where(AuthAuditEventModel.created_at <= created_to)
        statement = (
            statement.order_by(AuthAuditEventModel.created_at.desc(), AuthAuditEventModel.id)
            .limit(limit)
            .offset(offset)
        )
        return list((await self.session.scalars(statement)).all())

    async def cleanup(self, actor: AuthContext | None = None) -> int:
        site = await self.site.get()
        cutoff = datetime.now(UTC) - timedelta(days=site.audit_retention_days)
        result = await self.session.execute(
            delete(AuthAuditEventModel).where(AuthAuditEventModel.created_at < cutoff)
        )
        deleted = int(getattr(result, "rowcount", 0) or 0)
        self.auth.audit(
            "audit_cleanup_completed",
            "success",
            actor_user_id=actor.user.id if actor else None,
            subject_user_id=actor.user.id if actor else None,
            metadata={"deleted_count": deleted, "retention_days": site.audit_retention_days},
        )
        await self.session.commit()
        return deleted
