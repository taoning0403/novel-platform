from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from novel_platform.infrastructure.database.models import (
    AuthAuditEventModel,
    AuthSessionModel,
    DeviceModel,
    LoginThrottleModel,
    RefreshTokenModel,
)


class AuthRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add(self, model: Any) -> None:
        self.session.add(model)
        await self.session.flush()

    async def device_for_login(self, user_id: UUID, client_instance_id: UUID) -> DeviceModel | None:
        statement = (
            select(DeviceModel)
            .where(
                DeviceModel.user_id == user_id,
                DeviceModel.client_instance_id == client_instance_id,
            )
            .with_for_update()
        )
        return (await self.session.scalars(statement)).one_or_none()

    async def get_session(self, session_id: UUID) -> AuthSessionModel | None:
        return await self.session.get(AuthSessionModel, session_id)

    async def owned_session(self, user_id: UUID, session_id: UUID) -> AuthSessionModel | None:
        statement = select(AuthSessionModel).where(
            AuthSessionModel.id == session_id,
            AuthSessionModel.user_id == user_id,
        )
        return (await self.session.scalars(statement)).one_or_none()

    async def owned_device(self, user_id: UUID, device_id: UUID) -> DeviceModel | None:
        statement = select(DeviceModel).where(
            DeviceModel.id == device_id,
            DeviceModel.user_id == user_id,
        )
        return (await self.session.scalars(statement)).one_or_none()

    async def refresh_for_update(self, token_hash: str) -> RefreshTokenModel | None:
        statement = (
            select(RefreshTokenModel)
            .where(RefreshTokenModel.token_hash == token_hash)
            .with_for_update()
        )
        return (await self.session.scalars(statement)).one_or_none()

    async def list_sessions(self, user_id: UUID) -> list[tuple[AuthSessionModel, DeviceModel]]:
        statement = (
            select(AuthSessionModel, DeviceModel)
            .join(DeviceModel, DeviceModel.id == AuthSessionModel.device_id)
            .where(AuthSessionModel.user_id == user_id)
            .order_by(AuthSessionModel.created_at.desc(), AuthSessionModel.id)
        )
        return list((await self.session.execute(statement)).tuples().all())

    async def list_devices(self, user_id: UUID) -> list[tuple[DeviceModel, int]]:
        statement = (
            select(DeviceModel, func.count(AuthSessionModel.id))
            .outerjoin(
                AuthSessionModel,
                (AuthSessionModel.device_id == DeviceModel.id)
                & (AuthSessionModel.revoked_at.is_(None))
                & (AuthSessionModel.expires_at > datetime.now(UTC)),
            )
            .where(DeviceModel.user_id == user_id)
            .group_by(DeviceModel.id)
            .order_by(DeviceModel.last_seen_at.desc(), DeviceModel.id)
        )
        return [(device, count) for device, count in (await self.session.execute(statement)).all()]

    async def revoke_session(
        self,
        auth_session: AuthSessionModel,
        *,
        now: datetime,
        reason: str,
    ) -> None:
        if auth_session.revoked_at is None:
            auth_session.revoked_at = now
            auth_session.revoke_reason = reason
        await self.session.execute(
            update(RefreshTokenModel)
            .where(
                RefreshTokenModel.session_id == auth_session.id,
                RefreshTokenModel.revoked_at.is_(None),
            )
            .values(revoked_at=now)
        )

    async def revoke_user_sessions(self, user_id: UUID, *, now: datetime, reason: str) -> int:
        count = await self.session.scalar(
            select(func.count(AuthSessionModel.id)).where(
                AuthSessionModel.user_id == user_id,
                AuthSessionModel.revoked_at.is_(None),
            )
        )
        session_ids = select(AuthSessionModel.id).where(AuthSessionModel.user_id == user_id)
        await self.session.execute(
            update(RefreshTokenModel)
            .where(
                RefreshTokenModel.session_id.in_(session_ids),
                RefreshTokenModel.revoked_at.is_(None),
            )
            .values(revoked_at=now)
        )
        await self.session.execute(
            update(AuthSessionModel)
            .where(
                AuthSessionModel.user_id == user_id,
                AuthSessionModel.revoked_at.is_(None),
            )
            .values(revoked_at=now, revoke_reason=reason)
        )
        return int(count or 0)

    async def revoke_device_sessions(self, device_id: UUID, *, now: datetime, reason: str) -> int:
        count = await self.session.scalar(
            select(func.count(AuthSessionModel.id)).where(
                AuthSessionModel.device_id == device_id,
                AuthSessionModel.revoked_at.is_(None),
            )
        )
        session_ids = select(AuthSessionModel.id).where(AuthSessionModel.device_id == device_id)
        await self.session.execute(
            update(RefreshTokenModel)
            .where(
                RefreshTokenModel.session_id.in_(session_ids),
                RefreshTokenModel.revoked_at.is_(None),
            )
            .values(revoked_at=now)
        )
        await self.session.execute(
            update(AuthSessionModel)
            .where(
                AuthSessionModel.device_id == device_id,
                AuthSessionModel.revoked_at.is_(None),
            )
            .values(revoked_at=now, revoke_reason=reason)
        )
        return int(count or 0)

    async def revoke_credential_sessions(
        self, credential_id: UUID, *, now: datetime, reason: str
    ) -> int:
        sessions = list(
            (
                await self.session.scalars(
                    select(AuthSessionModel).where(
                        AuthSessionModel.access_credential_id == credential_id,
                        AuthSessionModel.revoked_at.is_(None),
                    )
                )
            ).all()
        )
        for auth_session in sessions:
            await self.revoke_session(auth_session, now=now, reason=reason)
        return len(sessions)

    async def revoke_passkey_sessions(self, passkey_id: UUID, *, now: datetime, reason: str) -> int:
        sessions = list(
            (
                await self.session.scalars(
                    select(AuthSessionModel).where(
                        AuthSessionModel.passkey_id == passkey_id,
                        AuthSessionModel.revoked_at.is_(None),
                    )
                )
            ).all()
        )
        for auth_session in sessions:
            await self.revoke_session(auth_session, now=now, reason=reason)
        return len(sessions)

    async def revoke_other_sessions(
        self, user_id: UUID, current_session_id: UUID, *, now: datetime
    ) -> int:
        sessions = list(
            (
                await self.session.scalars(
                    select(AuthSessionModel).where(
                        AuthSessionModel.user_id == user_id,
                        AuthSessionModel.id != current_session_id,
                        AuthSessionModel.revoked_at.is_(None),
                    )
                )
            ).all()
        )
        for auth_session in sessions:
            await self.revoke_session(auth_session, now=now, reason="revoke_others")
        return len(sessions)

    async def throttle_for_update(self, key_hash: str) -> LoginThrottleModel | None:
        statement = (
            select(LoginThrottleModel)
            .where(LoginThrottleModel.key_hash == key_hash)
            .with_for_update()
        )
        return (await self.session.scalars(statement)).one_or_none()

    async def clear_throttle(self, key_hash: str) -> None:
        await self.session.execute(
            delete(LoginThrottleModel).where(LoginThrottleModel.key_hash == key_hash)
        )

    def audit(
        self,
        event_type: str,
        outcome: str,
        *,
        actor_user_id: UUID | None = None,
        subject_user_id: UUID | None = None,
        session_id: UUID | None = None,
        device_id: UUID | None = None,
        access_credential_id: UUID | None = None,
        passkey_id: UUID | None = None,
        client_ip: str | None = None,
        user_agent_summary: str | None = None,
        metadata: dict[str, object] | None = None,
    ) -> None:
        self.session.add(
            AuthAuditEventModel(
                event_type=event_type,
                outcome=outcome,
                actor_user_id=actor_user_id,
                subject_user_id=subject_user_id,
                session_id=session_id,
                device_id=device_id,
                access_credential_id=access_credential_id,
                passkey_id=passkey_id,
                client_ip=client_ip,
                user_agent_summary=user_agent_summary,
                event_metadata=metadata or {},
            )
        )
