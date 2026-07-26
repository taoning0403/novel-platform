from dataclasses import dataclass
from datetime import UTC, datetime
from typing import cast
from uuid import UUID

from sqlalchemy import and_, case, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from novel_platform.infrastructure.database.models import (
    EditionTranslationRunModel,
    ProviderCredentialVersionModel,
    ProviderUsageRecordModel,
    UserModel,
)

PROVIDER_ID = "openai_compatible"


@dataclass(frozen=True, slots=True)
class UsageTotals:
    request_count: int
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


class ProviderCredentialRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def lock_user(self, user_id: UUID) -> None:
        statement = select(UserModel.id).where(UserModel.id == user_id).with_for_update()
        if (await self.session.scalar(statement)) is None:
            raise RuntimeError("Provider credential owner is missing")

    async def current(
        self,
        user_id: UUID,
        *,
        for_update: bool = False,
    ) -> ProviderCredentialVersionModel | None:
        statement = select(ProviderCredentialVersionModel).where(
            ProviderCredentialVersionModel.user_id == user_id,
            ProviderCredentialVersionModel.retired_at.is_(None),
            ProviderCredentialVersionModel.revoked_at.is_(None),
        )
        if for_update:
            statement = statement.with_for_update()
        return (await self.session.scalars(statement)).one_or_none()

    async def latest(self, user_id: UUID) -> ProviderCredentialVersionModel | None:
        statement = (
            select(ProviderCredentialVersionModel)
            .where(ProviderCredentialVersionModel.user_id == user_id)
            .order_by(
                ProviderCredentialVersionModel.version.desc(),
                ProviderCredentialVersionModel.id.desc(),
            )
            .limit(1)
        )
        return (await self.session.scalars(statement)).one_or_none()

    async def next_version(self, user_id: UUID) -> int:
        latest = await self.session.scalar(
            select(func.max(ProviderCredentialVersionModel.version)).where(
                ProviderCredentialVersionModel.user_id == user_id
            )
        )
        return int(latest or 0) + 1

    async def add(
        self,
        credential: ProviderCredentialVersionModel,
    ) -> ProviderCredentialVersionModel:
        self.session.add(credential)
        await self.session.flush()
        return credential

    async def resolve_usable(
        self,
        credential_scope: UUID,
        *,
        for_update: bool = False,
    ) -> ProviderCredentialVersionModel | None:
        statement = select(ProviderCredentialVersionModel).where(
            ProviderCredentialVersionModel.id == credential_scope,
            ProviderCredentialVersionModel.revoked_at.is_(None),
        )
        if for_update:
            statement = statement.with_for_update()
        return (await self.session.scalars(statement)).one_or_none()

    async def resolve_for_relay(
        self,
        credential_scope: UUID,
        *,
        remote_job_id: str,
    ) -> ProviderCredentialVersionModel | None:
        eligible_statuses = (
            "preparing",
            "queued",
            "running",
            "paused",
            "cancelling",
            "attention_required",
        )
        statement = (
            select(
                ProviderCredentialVersionModel,
                EditionTranslationRunModel,
            )
            .join(
                EditionTranslationRunModel,
                EditionTranslationRunModel.provider_credential_version_id
                == ProviderCredentialVersionModel.id,
            )
            .where(
                ProviderCredentialVersionModel.id == credential_scope,
                ProviderCredentialVersionModel.revoked_at.is_(None),
                ProviderCredentialVersionModel.user_id
                == EditionTranslationRunModel.created_by_user_id,
                EditionTranslationRunModel.status.in_(eligible_statuses),
                or_(
                    EditionTranslationRunModel.remote_job_id == remote_job_id,
                    and_(
                        EditionTranslationRunModel.remote_job_id.is_(None),
                        EditionTranslationRunModel.status == "preparing",
                    ),
                ),
            )
            .order_by(
                case(
                    (EditionTranslationRunModel.remote_job_id == remote_job_id, 0),
                    else_=1,
                )
            )
            .with_for_update(of=EditionTranslationRunModel)
            .limit(1)
        )
        resolved = (await self.session.execute(statement)).one_or_none()
        if resolved is None:
            return None
        credential = cast(ProviderCredentialVersionModel, resolved[0])
        run = cast(EditionTranslationRunModel, resolved[1])
        if run.remote_job_id is None:
            run.remote_job_id = remote_job_id
            run.updated_at = datetime.now(UTC)
            await self.session.flush()
        return credential

    async def revoke_all(self, user_id: UUID, *, now: datetime) -> int:
        result = await self.session.execute(
            update(ProviderCredentialVersionModel)
            .where(
                ProviderCredentialVersionModel.user_id == user_id,
                ProviderCredentialVersionModel.revoked_at.is_(None),
            )
            .values(revoked_at=now)
        )
        return int(getattr(result, "rowcount", 0) or 0)

    async def add_usage(
        self,
        *,
        credential: ProviderCredentialVersionModel,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        total_tokens: int,
        remote_job_id: str | None,
    ) -> None:
        self.session.add(
            ProviderUsageRecordModel(
                provider_credential_version_id=credential.id,
                model=model,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens,
                remote_job_id=remote_job_id,
            )
        )
        await self.session.flush()

    async def usage_totals(
        self,
        user_id: UUID,
        *,
        created_from: datetime | None = None,
    ) -> UsageTotals:
        statement = (
            select(
                func.count(ProviderUsageRecordModel.id),
                func.coalesce(func.sum(ProviderUsageRecordModel.prompt_tokens), 0),
                func.coalesce(func.sum(ProviderUsageRecordModel.completion_tokens), 0),
                func.coalesce(func.sum(ProviderUsageRecordModel.total_tokens), 0),
            )
            .join(
                ProviderCredentialVersionModel,
                ProviderCredentialVersionModel.id
                == ProviderUsageRecordModel.provider_credential_version_id,
            )
            .where(ProviderCredentialVersionModel.user_id == user_id)
        )
        if created_from is not None:
            statement = statement.where(ProviderUsageRecordModel.created_at >= created_from)
        values = (await self.session.execute(statement)).one()
        return UsageTotals(
            request_count=int(values[0]),
            prompt_tokens=int(values[1]),
            completion_tokens=int(values[2]),
            total_tokens=int(values[3]),
        )

    async def all_time_and_current_month(
        self,
        user_id: UUID,
        *,
        now: datetime | None = None,
    ) -> tuple[UsageTotals, UsageTotals]:
        current = now or datetime.now(UTC)
        month_start = datetime(current.year, current.month, 1, tzinfo=UTC)
        return (
            await self.usage_totals(user_id),
            await self.usage_totals(user_id, created_from=month_start),
        )
