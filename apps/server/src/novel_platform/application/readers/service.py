from dataclasses import dataclass
from datetime import UTC, datetime
from http import HTTPStatus
from uuid import UUID, uuid4

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from novel_platform.application.auth.context import AuthContext
from novel_platform.application.auth.security import TokenService
from novel_platform.application.errors import ApplicationError
from novel_platform.config import Settings
from novel_platform.domain.auth.capabilities import (
    CredentialCapability,
    validate_credential_capabilities,
)
from novel_platform.domain.auth.models import AccessCredentialStatus, UserRole, UserStatus
from novel_platform.domain.auth.rules import normalize_display_name
from novel_platform.infrastructure.database.models import (
    AuthAuditEventModel,
    DeviceModel,
    ReaderAccessCredentialModel,
    UserModel,
)
from novel_platform.infrastructure.repositories.auth import AuthRepository
from novel_platform.infrastructure.repositories.credentials import CredentialRepository
from novel_platform.infrastructure.repositories.site import SiteRepository
from novel_platform.infrastructure.repositories.users import UserRepository


@dataclass(frozen=True, slots=True)
class IssuedReaderCredential:
    user: UserModel
    credential: ReaderAccessCredentialModel
    raw_credential: str
    capabilities: frozenset[CredentialCapability]


ReaderRecord = tuple[
    UserModel,
    ReaderAccessCredentialModel | None,
    int,
    frozenset[CredentialCapability],
]


class ReaderManagementService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self.settings = settings
        self.users = UserRepository(session)
        self.credentials = CredentialRepository(session)
        self.auth = AuthRepository(session)
        self.site = SiteRepository(session)
        self.tokens = TokenService(settings)

    async def list_readers(
        self,
    ) -> list[ReaderRecord]:
        users = list(
            (
                await self.session.scalars(
                    select(UserModel)
                    .where(
                        UserModel.role == UserRole.MEMBER,
                        UserModel.status != UserStatus.PENDING_SETUP,
                    )
                    .order_by(UserModel.created_at.asc(), UserModel.id)
                )
            ).all()
        )
        rows: list[ReaderRecord] = []
        for user in users:
            credential = await self.credentials.current_reader_credential(user.id)
            device_count = (
                await self.credentials.active_device_count(credential.id) if credential else 0
            )
            capabilities = (
                await self.credentials.capabilities(credential.id)
                if credential is not None
                else frozenset()
            )
            rows.append((user, credential, device_count, capabilities))
        return rows

    async def get_reader(self, user_id: UUID) -> ReaderRecord:
        user = await self.users.get(user_id)
        if user is None or user.role != UserRole.MEMBER:
            raise ApplicationError(
                "reader_not_found", "阅读者不存在。", status_code=HTTPStatus.NOT_FOUND
            )
        credential = await self.credentials.current_reader_credential(user.id)
        device_count = (
            await self.credentials.active_device_count(credential.id) if credential else 0
        )
        capabilities = (
            await self.credentials.capabilities(credential.id)
            if credential is not None
            else frozenset()
        )
        return user, credential, device_count, capabilities

    async def create_reader(
        self,
        actor: AuthContext,
        *,
        display_name: str,
        admin_note: str | None,
        expires_at: datetime,
        max_devices: int | None,
        allow_new_devices: bool,
        capabilities: list[CredentialCapability],
    ) -> IssuedReaderCredential:
        now = datetime.now(UTC)
        self._validate_expiry(expires_at, now)
        capability_snapshot = self._validate_capabilities(capabilities)
        site = await self.site.get()
        user_id = uuid4()
        internal_username = f"reader-{user_id.hex}"
        user = UserModel(
            id=user_id,
            username=internal_username,
            normalized_username=internal_username,
            display_name=normalize_display_name(display_name),
            admin_note=admin_note.strip() if admin_note else None,
            role=UserRole.MEMBER,
            status=UserStatus.ACTIVE,
            password_hash=None,
            created_at=now,
            updated_at=now,
        )
        await self.users.add(user)
        issued = await self._issue(
            user=user,
            actor=actor,
            expires_at=expires_at,
            max_devices=max_devices or site.default_reader_max_devices,
            allow_new_devices=allow_new_devices,
            capabilities=capability_snapshot,
            now=now,
        )
        self.auth.audit(
            "reader_created",
            "success",
            actor_user_id=actor.user.id,
            subject_user_id=user.id,
            access_credential_id=issued.credential.id,
        )
        await self.session.commit()
        return issued

    async def update_reader(
        self,
        actor: AuthContext,
        user_id: UUID,
        *,
        display_name: str | None,
        admin_note: str | None,
        admin_note_set: bool,
        expires_at: datetime | None,
        max_devices: int | None,
        allow_new_devices: bool | None,
    ) -> ReaderRecord:
        user, credential, _, _ = await self.get_reader(user_id)
        now = datetime.now(UTC)
        changed: list[str] = []
        expiry_event: str | None = None
        if display_name is not None:
            user.display_name = normalize_display_name(display_name)
            changed.append("display_name")
        if admin_note_set:
            user.admin_note = admin_note.strip() if admin_note else None
            changed.append("admin_note")
        if any(value is not None for value in (expires_at, max_devices, allow_new_devices)):
            if credential is None:
                raise ApplicationError(
                    "reader_credential_missing",
                    "该阅读者尚未签发访问凭证。",
                    status_code=HTTPStatus.CONFLICT,
                )
            if credential.status == AccessCredentialStatus.REVOKED:
                raise ApplicationError(
                    "credential_revoked",
                    "已撤销的凭证不能修改。",
                    status_code=HTTPStatus.CONFLICT,
                )
            if expires_at is not None:
                if expires_at > credential.expires_at:
                    expiry_event = "credential_expiry_extended"
                elif expires_at < credential.expires_at:
                    expiry_event = "credential_expiry_shortened"
                credential.expires_at = expires_at
                changed.append("expires_at")
            if max_devices is not None:
                if max_devices < 1:
                    raise ApplicationError("validation_error", "设备上限必须是正整数。")
                credential.max_devices = max_devices
                changed.append("max_devices")
            if allow_new_devices is not None:
                credential.allow_new_devices = allow_new_devices
                changed.append("allow_new_devices")
            credential.updated_by_admin_id = actor.user.id
            credential.updated_at = now
            if credential.expires_at <= now:
                await self.auth.revoke_credential_sessions(
                    credential.id, now=now, reason="credential_expired"
                )
        if not changed:
            raise ApplicationError("validation_error", "至少需要修改一个字段。")
        user.updated_at = now
        self.auth.audit(
            "reader_updated",
            "success",
            actor_user_id=actor.user.id,
            subject_user_id=user.id,
            access_credential_id=credential.id if credential else None,
            metadata={"fields": sorted(changed)},
        )
        if expiry_event is not None and credential is not None:
            self.auth.audit(
                expiry_event,
                "success",
                actor_user_id=actor.user.id,
                subject_user_id=user.id,
                access_credential_id=credential.id,
            )
        await self.session.commit()
        return await self.get_reader(user.id)

    async def suspend(self, actor: AuthContext, user_id: UUID) -> None:
        user, credential = await self._current_for_update(user_id)
        if credential.status == AccessCredentialStatus.REVOKED:
            raise ApplicationError(
                "credential_revoked", "已撤销凭证不能暂停。", status_code=HTTPStatus.CONFLICT
            )
        now = datetime.now(UTC)
        credential.status = AccessCredentialStatus.SUSPENDED
        credential.suspended_at = now
        credential.updated_at = now
        credential.updated_by_admin_id = actor.user.id
        await self.auth.revoke_credential_sessions(
            credential.id, now=now, reason="credential_suspended"
        )
        self._audit_credential("credential_suspended", actor, user, credential)
        await self.session.commit()

    async def resume(self, actor: AuthContext, user_id: UUID) -> None:
        user, credential = await self._current_for_update(user_id)
        if credential.status != AccessCredentialStatus.SUSPENDED:
            raise ApplicationError(
                "credential_not_suspended",
                "只有暂停中的凭证可以恢复。",
                status_code=HTTPStatus.CONFLICT,
            )
        credential.status = AccessCredentialStatus.ACTIVE
        credential.suspended_at = None
        credential.updated_at = datetime.now(UTC)
        credential.updated_by_admin_id = actor.user.id
        self._audit_credential("credential_resumed", actor, user, credential)
        await self.session.commit()

    async def revoke(self, actor: AuthContext, user_id: UUID) -> None:
        user, credential = await self._current_for_update(user_id)
        await self._revoke_credential(actor, user, credential, reason="credential_revoked")
        await self.session.commit()

    async def reissue(
        self,
        actor: AuthContext,
        user_id: UUID,
        *,
        expires_at: datetime,
        max_devices: int | None,
        allow_new_devices: bool,
        capabilities: list[CredentialCapability],
    ) -> IssuedReaderCredential:
        user, current, _, _ = await self.get_reader(user_id)
        now = datetime.now(UTC)
        self._validate_expiry(expires_at, now)
        capability_snapshot = self._validate_capabilities(capabilities)
        site = await self.site.get()
        if current is not None:
            await self._revoke_credential(actor, user, current, reason="credential_reissued")
            current.reissued_at = now
        issued = await self._issue(
            user=user,
            actor=actor,
            expires_at=expires_at,
            max_devices=max_devices or site.default_reader_max_devices,
            allow_new_devices=allow_new_devices,
            capabilities=capability_snapshot,
            now=now,
        )
        if current is not None:
            current.replaced_by_credential_id = issued.credential.id
        self.auth.audit(
            "credential_reissued",
            "success",
            actor_user_id=actor.user.id,
            subject_user_id=user.id,
            access_credential_id=issued.credential.id,
            metadata={"capabilities": sorted(item.value for item in issued.capabilities)},
        )
        await self.session.commit()
        return issued

    async def revoke_all_sessions(self, actor: AuthContext, user_id: UUID) -> int:
        user, credential, _, _ = await self.get_reader(user_id)
        if credential is None:
            return 0
        count = await self.auth.revoke_credential_sessions(
            credential.id, now=datetime.now(UTC), reason="admin_revoke_reader_sessions"
        )
        self.auth.audit(
            "reader_sessions_revoked_all",
            "success",
            actor_user_id=actor.user.id,
            subject_user_id=user.id,
            access_credential_id=credential.id,
            metadata={"revoked_count": count},
        )
        await self.session.commit()
        return count

    async def list_devices(self, user_id: UUID) -> list[tuple[DeviceModel, int]]:
        user, _, _, _ = await self.get_reader(user_id)
        return await self.auth.list_devices(user.id)

    async def revoke_device(self, actor: AuthContext, user_id: UUID, device_id: UUID) -> None:
        user, _, _, _ = await self.get_reader(user_id)
        device = await self.auth.owned_device(user.id, device_id)
        if device is None:
            raise ApplicationError(
                "device_not_found", "设备不存在。", status_code=HTTPStatus.NOT_FOUND
            )
        now = datetime.now(UTC)
        device.revoked_at = device.revoked_at or now
        device.updated_at = now
        await self.auth.revoke_device_sessions(device.id, now=now, reason="admin_device_revoked")
        self.auth.audit(
            "device_revoked",
            "success",
            actor_user_id=actor.user.id,
            subject_user_id=user.id,
            device_id=device.id,
            access_credential_id=device.access_credential_id,
        )
        await self.session.commit()

    async def audit_events(self, user_id: UUID, *, limit: int = 100) -> list[AuthAuditEventModel]:
        await self.get_reader(user_id)
        statement = (
            select(AuthAuditEventModel)
            .where(AuthAuditEventModel.subject_user_id == user_id)
            .order_by(AuthAuditEventModel.created_at.desc())
            .limit(limit)
        )
        return list((await self.session.scalars(statement)).all())

    async def _issue(
        self,
        *,
        user: UserModel,
        actor: AuthContext,
        expires_at: datetime,
        max_devices: int,
        allow_new_devices: bool,
        capabilities: frozenset[CredentialCapability],
        now: datetime,
    ) -> IssuedReaderCredential:
        if max_devices < 1:
            raise ApplicationError("validation_error", "设备上限必须是正整数。")
        raw, token_hash, hint = self.tokens.new_access_credential()
        credential = ReaderAccessCredentialModel(
            user_id=user.id,
            token_hash=token_hash,
            credential_hint=hint,
            status=AccessCredentialStatus.ACTIVE,
            expires_at=expires_at,
            allow_new_devices=allow_new_devices,
            max_devices=max_devices,
            created_by_admin_id=actor.user.id,
            updated_by_admin_id=actor.user.id,
            created_at=now,
            updated_at=now,
        )
        self.session.add(credential)
        await self.session.flush()
        await self.credentials.add_capabilities(credential.id, capabilities)
        self.auth.audit(
            "credential_created",
            "success",
            actor_user_id=actor.user.id,
            subject_user_id=user.id,
            access_credential_id=credential.id,
            metadata={"capabilities": sorted(item.value for item in capabilities)},
        )
        return IssuedReaderCredential(user, credential, raw, capabilities)

    async def _current_for_update(
        self, user_id: UUID
    ) -> tuple[UserModel, ReaderAccessCredentialModel]:
        user, _, _, _ = await self.get_reader(user_id)
        credential = await self.credentials.current_reader_credential(user.id, for_update=True)
        if credential is None:
            raise ApplicationError(
                "reader_credential_missing",
                "该阅读者尚未签发访问凭证。",
                status_code=HTTPStatus.CONFLICT,
            )
        return user, credential

    async def _revoke_credential(
        self,
        actor: AuthContext,
        user: UserModel,
        credential: ReaderAccessCredentialModel,
        *,
        reason: str,
    ) -> None:
        if credential.status == AccessCredentialStatus.REVOKED:
            raise ApplicationError(
                "credential_revoked", "凭证已经永久撤销。", status_code=HTTPStatus.CONFLICT
            )
        now = datetime.now(UTC)
        credential.status = AccessCredentialStatus.REVOKED
        credential.revoked_at = now
        credential.updated_at = now
        credential.updated_by_admin_id = actor.user.id
        await self.auth.revoke_credential_sessions(credential.id, now=now, reason=reason)
        await self.session.execute(
            update(DeviceModel)
            .where(
                DeviceModel.access_credential_id == credential.id,
                DeviceModel.revoked_at.is_(None),
            )
            .values(revoked_at=now, updated_at=now)
        )
        self._audit_credential(reason, actor, user, credential)

    def _audit_credential(
        self,
        event_type: str,
        actor: AuthContext,
        user: UserModel,
        credential: ReaderAccessCredentialModel,
    ) -> None:
        self.auth.audit(
            event_type,
            "success",
            actor_user_id=actor.user.id,
            subject_user_id=user.id,
            access_credential_id=credential.id,
        )

    @staticmethod
    def _validate_expiry(expires_at: datetime, now: datetime) -> None:
        if expires_at <= now:
            raise ApplicationError("validation_error", "凭证有效期必须晚于当前时间。")

    @staticmethod
    def _validate_capabilities(
        capabilities: list[CredentialCapability],
    ) -> frozenset[CredentialCapability]:
        try:
            return validate_credential_capabilities(capabilities)
        except ValueError as error:
            raise ApplicationError(
                "invalid_credential_capabilities",
                "访问权限集合无效。",
                status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
            ) from error
