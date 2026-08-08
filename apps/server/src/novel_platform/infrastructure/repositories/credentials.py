from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from novel_platform.domain.auth.capabilities import CredentialCapability
from novel_platform.domain.auth.models import AccessCredentialStatus, WebAuthnChallengePurpose
from novel_platform.infrastructure.database.models import (
    AdminPasskeyModel,
    AdminRecoveryCredentialModel,
    DeviceModel,
    ReaderAccessCredentialModel,
    ReaderCredentialCapabilityModel,
    WebAuthnChallengeModel,
)


class CredentialRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def reader_for_token_hash(
        self, token_hash: str, *, for_update: bool = False
    ) -> ReaderAccessCredentialModel | None:
        statement = select(ReaderAccessCredentialModel).where(
            ReaderAccessCredentialModel.token_hash == token_hash
        )
        if for_update:
            statement = statement.with_for_update()
        return (await self.session.scalars(statement)).one_or_none()

    async def current_reader_credential(
        self, user_id: UUID, *, for_update: bool = False
    ) -> ReaderAccessCredentialModel | None:
        statement = select(ReaderAccessCredentialModel).where(
            ReaderAccessCredentialModel.user_id == user_id,
            ReaderAccessCredentialModel.status != AccessCredentialStatus.REVOKED,
        )
        if for_update:
            statement = statement.with_for_update()
        return (await self.session.scalars(statement)).one_or_none()

    async def reader_credentials(self, user_id: UUID) -> list[ReaderAccessCredentialModel]:
        statement = (
            select(ReaderAccessCredentialModel)
            .where(ReaderAccessCredentialModel.user_id == user_id)
            .order_by(ReaderAccessCredentialModel.created_at.desc())
        )
        return list((await self.session.scalars(statement)).all())

    async def capabilities(self, credential_id: UUID) -> frozenset[CredentialCapability]:
        statement = (
            select(ReaderCredentialCapabilityModel.capability)
            .where(ReaderCredentialCapabilityModel.credential_id == credential_id)
            .order_by(ReaderCredentialCapabilityModel.capability)
        )
        return frozenset(
            CredentialCapability(value) for value in await self.session.scalars(statement)
        )

    async def add_capabilities(
        self,
        credential_id: UUID,
        capabilities: frozenset[CredentialCapability],
    ) -> None:
        self.session.add_all(
            ReaderCredentialCapabilityModel(
                credential_id=credential_id,
                capability=capability.value,
            )
            for capability in capabilities
        )
        await self.session.flush()

    async def recovery_for_token_hash(
        self, token_hash: str, *, for_update: bool = False
    ) -> AdminRecoveryCredentialModel | None:
        statement = select(AdminRecoveryCredentialModel).where(
            AdminRecoveryCredentialModel.token_hash == token_hash
        )
        if for_update:
            statement = statement.with_for_update()
        return (await self.session.scalars(statement)).one_or_none()

    async def device_by_secret_hash(self, secret_hash: str) -> DeviceModel | None:
        statement = select(DeviceModel).where(DeviceModel.device_secret_hash == secret_hash)
        return (await self.session.scalars(statement)).one_or_none()

    async def active_device_count(self, access_credential_id: UUID) -> int:
        count = await self.session.scalar(
            select(func.count(DeviceModel.id)).where(
                DeviceModel.access_credential_id == access_credential_id,
                DeviceModel.revoked_at.is_(None),
            )
        )
        return int(count or 0)

    async def list_passkeys(self, user_id: UUID) -> list[AdminPasskeyModel]:
        statement = (
            select(AdminPasskeyModel)
            .where(AdminPasskeyModel.user_id == user_id)
            .order_by(AdminPasskeyModel.created_at.asc(), AdminPasskeyModel.id)
        )
        return list((await self.session.scalars(statement)).all())

    async def active_passkey_count(self, user_id: UUID) -> int:
        count = await self.session.scalar(
            select(func.count(AdminPasskeyModel.id)).where(
                AdminPasskeyModel.user_id == user_id,
                AdminPasskeyModel.revoked_at.is_(None),
            )
        )
        return int(count or 0)

    async def passkey_by_credential_id(
        self, credential_id: bytes, *, for_update: bool = False
    ) -> AdminPasskeyModel | None:
        statement = select(AdminPasskeyModel).where(
            AdminPasskeyModel.credential_id == credential_id
        )
        if for_update:
            statement = statement.with_for_update()
        return (await self.session.scalars(statement)).one_or_none()

    async def passkey(self, user_id: UUID, passkey_id: UUID) -> AdminPasskeyModel | None:
        statement = select(AdminPasskeyModel).where(
            AdminPasskeyModel.id == passkey_id,
            AdminPasskeyModel.user_id == user_id,
        )
        return (await self.session.scalars(statement)).one_or_none()

    async def challenge_for_update(
        self, challenge_id: UUID, purpose: WebAuthnChallengePurpose
    ) -> WebAuthnChallengeModel | None:
        statement = (
            select(WebAuthnChallengeModel)
            .where(
                WebAuthnChallengeModel.id == challenge_id,
                WebAuthnChallengeModel.purpose == purpose,
            )
            .with_for_update()
        )
        return (await self.session.scalars(statement)).one_or_none()

    async def delete_expired_challenges(
        self, *, now: datetime | None = None, batch_size: int = 500
    ) -> int:
        cutoff = now or datetime.now(UTC)
        batch = (
            select(WebAuthnChallengeModel.id)
            .where(WebAuthnChallengeModel.expires_at <= cutoff)
            .order_by(WebAuthnChallengeModel.expires_at)
            .limit(batch_size)
        )
        result = await self.session.execute(
            delete(WebAuthnChallengeModel).where(WebAuthnChallengeModel.id.in_(batch))
        )
        return int(getattr(result, "rowcount", 0) or 0)
