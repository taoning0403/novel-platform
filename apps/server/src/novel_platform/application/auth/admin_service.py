from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from http import HTTPStatus

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from novel_platform.application.auth.security import TokenService
from novel_platform.application.errors import ApplicationError
from novel_platform.config import Settings
from novel_platform.domain.auth.models import AdminRecoveryPurpose, UserRole, UserStatus
from novel_platform.domain.auth.rules import normalize_display_name
from novel_platform.infrastructure.database.models import (
    AdminPasskeyModel,
    AdminRecoveryCredentialModel,
    AuthSessionModel,
    SiteSettingsModel,
    UserModel,
)
from novel_platform.infrastructure.repositories.auth import AuthRepository
from novel_platform.infrastructure.repositories.site import SiteRepository
from novel_platform.infrastructure.repositories.users import UserRepository


@dataclass(frozen=True, slots=True)
class IssuedRecoveryCredential:
    credential: str
    expires_at: datetime
    purpose: AdminRecoveryPurpose


@dataclass(frozen=True, slots=True)
class AdminStatus:
    initialized: bool
    admin_user_id: str | None
    display_name: str | None
    locked: bool
    active_passkeys: int
    active_sessions: int
    migration_completed: bool


class AdminService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self.settings = settings
        self.users = UserRepository(session)
        self.site = SiteRepository(session)
        self.auth = AuthRepository(session)
        self.tokens = TokenService(settings)

    async def initialize(self, display_name: str) -> IssuedRecoveryCredential:
        pending = await self.users.pending_setup_for_update()
        if pending is None:
            raise ApplicationError(
                "admin_already_initialized",
                "管理员已经完成初始化。",
                status_code=HTTPStatus.CONFLICT,
            )
        existing_admins = await self.users.active_admins_for_update()
        if existing_admins:
            raise ApplicationError(
                "admin_already_initialized",
                "管理员已经完成初始化。",
                status_code=HTTPStatus.CONFLICT,
            )
        now = datetime.now(UTC)
        pending.username = "__site_admin__"
        pending.normalized_username = "__site_admin__"
        pending.display_name = normalize_display_name(display_name)
        pending.role = UserRole.ADMIN
        pending.status = UserStatus.ACTIVE
        pending.password_hash = None
        pending.password_changed_at = now
        pending.updated_at = now
        site = await self.site.get(for_update=True)
        site.library_owner_user_id = pending.id
        site.migration_completed_at = now
        site.updated_at = now
        issued = await self._issue_recovery(pending, AdminRecoveryPurpose.INITIALIZE, now)
        self.auth.audit(
            "admin_initialized",
            "success",
            actor_user_id=pending.id,
            subject_user_id=pending.id,
        )
        await self.session.commit()
        return issued

    async def create_recovery(self) -> IssuedRecoveryCredential:
        site, admin = await self._site_admin(for_update=True)
        if site.admin_locked_at is not None:
            purpose = AdminRecoveryPurpose.RECOVERY
        else:
            purpose = AdminRecoveryPurpose.RECOVERY
        now = datetime.now(UTC)
        issued = await self._issue_recovery(admin, purpose, now)
        self.auth.audit(
            "admin_recovery_created",
            "success",
            subject_user_id=admin.id,
        )
        await self.session.commit()
        return issued

    async def reset_credentials(self) -> IssuedRecoveryCredential:
        _, admin = await self._site_admin(for_update=True)
        now = datetime.now(UTC)
        await self.session.execute(
            update(AdminPasskeyModel)
            .where(AdminPasskeyModel.user_id == admin.id, AdminPasskeyModel.revoked_at.is_(None))
            .values(revoked_at=now, updated_at=now)
        )
        await self.auth.revoke_user_sessions(admin.id, now=now, reason="admin_credentials_reset")
        issued = await self._issue_recovery(admin, AdminRecoveryPurpose.CREDENTIAL_RESET, now)
        self.auth.audit(
            "admin_credentials_reset",
            "success",
            subject_user_id=admin.id,
        )
        await self.session.commit()
        return issued

    async def revoke_all_sessions(self) -> int:
        _, admin = await self._site_admin(for_update=True)
        now = datetime.now(UTC)
        count = await self.auth.revoke_user_sessions(admin.id, now=now, reason="admin_revoke_all")
        self.auth.audit(
            "admin_sessions_revoked_all",
            "success",
            subject_user_id=admin.id,
            metadata={"revoked_count": count},
        )
        await self.session.commit()
        return count

    async def lock(self) -> None:
        site, admin = await self._site_admin(for_update=True)
        now = datetime.now(UTC)
        if site.admin_locked_at is None:
            site.admin_locked_at = now
            site.updated_at = now
        await self.auth.revoke_user_sessions(admin.id, now=now, reason="admin_locked")
        self.auth.audit("admin_locked", "success", subject_user_id=admin.id)
        await self.session.commit()

    async def unlock(self) -> None:
        site, admin = await self._site_admin(for_update=True)
        site.admin_locked_at = None
        site.updated_at = datetime.now(UTC)
        self.auth.audit("admin_unlocked", "success", subject_user_id=admin.id)
        await self.session.commit()

    async def status(self) -> AdminStatus:
        site = await self.site.get()
        if site.library_owner_user_id is None:
            return AdminStatus(False, None, None, False, 0, 0, False)
        admin = await self.session.get(UserModel, site.library_owner_user_id)
        if admin is None:
            raise RuntimeError("configured library owner is missing")
        now = datetime.now(UTC)
        passkeys = await self.session.scalar(
            select(func.count(AdminPasskeyModel.id)).where(
                AdminPasskeyModel.user_id == admin.id,
                AdminPasskeyModel.revoked_at.is_(None),
            )
        )
        sessions = await self.session.scalar(
            select(func.count(AuthSessionModel.id)).where(
                AuthSessionModel.user_id == admin.id,
                AuthSessionModel.revoked_at.is_(None),
                AuthSessionModel.expires_at > now,
            )
        )
        return AdminStatus(
            initialized=admin.status == UserStatus.ACTIVE,
            admin_user_id=str(admin.id),
            display_name=admin.display_name,
            locked=site.admin_locked_at is not None,
            active_passkeys=int(passkeys or 0),
            active_sessions=int(sessions or 0),
            migration_completed=site.migration_completed_at is not None,
        )

    async def _issue_recovery(
        self, admin: UserModel, purpose: AdminRecoveryPurpose, now: datetime
    ) -> IssuedRecoveryCredential:
        await self.session.execute(
            update(AdminRecoveryCredentialModel)
            .where(
                AdminRecoveryCredentialModel.user_id == admin.id,
                AdminRecoveryCredentialModel.used_at.is_(None),
                AdminRecoveryCredentialModel.revoked_at.is_(None),
            )
            .values(revoked_at=now)
        )
        raw, token_hash, hint = self.tokens.new_recovery_credential()
        expires_at = now + timedelta(minutes=self.settings.admin_recovery_ttl_minutes)
        credential = AdminRecoveryCredentialModel(
            user_id=admin.id,
            token_hash=token_hash,
            credential_hint=hint,
            purpose=purpose,
            expires_at=expires_at,
            created_at=now,
        )
        self.session.add(credential)
        await self.session.flush()
        return IssuedRecoveryCredential(raw, expires_at, purpose)

    async def _site_admin(self, *, for_update: bool) -> tuple[SiteSettingsModel, UserModel]:
        site = await self.site.get(for_update=for_update)
        if site.library_owner_user_id is None:
            raise ApplicationError(
                "admin_not_initialized",
                "管理员尚未初始化。",
                status_code=HTTPStatus.CONFLICT,
            )
        admin = await self.session.get(UserModel, site.library_owner_user_id)
        if admin is None or admin.role != UserRole.ADMIN:
            raise RuntimeError("configured library owner is not an administrator")
        return site, admin
