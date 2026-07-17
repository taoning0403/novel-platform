import hmac
from datetime import UTC, datetime, timedelta
from http import HTTPStatus
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from novel_platform.application.auth.commands import CredentialLogin, LoginDevice
from novel_platform.application.auth.context import AuthContext, TokenResult
from novel_platform.application.auth.security import TokenService
from novel_platform.application.errors import ApplicationError
from novel_platform.config import Settings
from novel_platform.domain.auth.models import AccessCredentialStatus, UserRole, UserStatus
from novel_platform.infrastructure.database.models import (
    AdminPasskeyModel,
    AdminRecoveryCredentialModel,
    AuthSessionModel,
    DeviceModel,
    LoginThrottleModel,
    ReaderAccessCredentialModel,
    RefreshTokenModel,
    UserModel,
)
from novel_platform.infrastructure.repositories.auth import AuthRepository
from novel_platform.infrastructure.repositories.credentials import CredentialRepository
from novel_platform.infrastructure.repositories.site import SiteRepository
from novel_platform.infrastructure.repositories.users import UserRepository

GENERIC_CREDENTIAL_ERROR = "访问凭证无效、已过期或当前不可用。"


class AuthService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self.settings = settings
        self.users = UserRepository(session)
        self.auth = AuthRepository(session)
        self.credentials = CredentialRepository(session)
        self.site = SiteRepository(session)
        self.tokens = TokenService(settings)

    async def credential_login(self, command: CredentialLogin) -> TokenResult:
        reader_hash = self.tokens.hash_access_credential(command.credential)
        recovery_hash = self.tokens.hash_recovery_credential(command.credential)
        throttle_keys = sorted(
            {
                self.tokens.hash_login_ip(command.client_ip),
                self.tokens.hash_login_credential(reader_hash),
            }
        )
        now = datetime.now(UTC)
        throttles = [await self.auth.throttle_for_update(key) for key in throttle_keys]
        if any(
            throttle is not None
            and throttle.blocked_until is not None
            and throttle.blocked_until > now
            for throttle in throttles
        ):
            self.auth.audit(
                "login_rate_limited",
                "failure",
                client_ip=self._ip(command.client_ip),
                user_agent_summary=self._user_agent(command.user_agent),
            )
            await self.session.commit()
            raise ApplicationError(
                "login_temporarily_blocked",
                "登录尝试过多，请稍后再试。",
                status_code=HTTPStatus.TOO_MANY_REQUESTS,
            )

        reader = await self.credentials.reader_for_token_hash(reader_hash, for_update=True)
        recovery = await self.credentials.recovery_for_token_hash(recovery_hash, for_update=True)
        if reader is not None and await self._reader_credential_valid(reader, now):
            result = await self._reader_login(reader, command, now)
        elif recovery is not None and await self._recovery_credential_valid(recovery, now):
            result = await self._recovery_login(recovery, command, now)
        else:
            blocked = await self._record_login_failure(throttle_keys, throttles, now)
            if recovery is not None:
                if recovery.used_at is not None:
                    recovery_event = "admin_recovery_reused"
                elif recovery.expires_at <= now:
                    recovery_event = "admin_recovery_expired"
                else:
                    recovery_event = "admin_recovery_unavailable"
                self.auth.audit(
                    recovery_event,
                    "failure",
                    subject_user_id=recovery.user_id,
                    client_ip=self._ip(command.client_ip),
                    user_agent_summary=self._user_agent(command.user_agent),
                )
            self.auth.audit(
                "login_failed",
                "failure",
                subject_user_id=(
                    reader.user_id if reader else recovery.user_id if recovery else None
                ),
                client_ip=self._ip(command.client_ip),
                user_agent_summary=self._user_agent(command.user_agent),
            )
            await self.session.commit()
            if blocked:
                raise ApplicationError(
                    "login_temporarily_blocked",
                    "登录尝试过多，请稍后再试。",
                    status_code=HTTPStatus.TOO_MANY_REQUESTS,
                )
            raise self.invalid_credential()

        for key in throttle_keys:
            await self.auth.clear_throttle(key)
        await self.session.commit()
        return result

    async def create_passkey_session(
        self,
        *,
        user: UserModel,
        passkey: AdminPasskeyModel,
        device_input: LoginDevice,
        client_ip: str,
        user_agent: str | None,
        device_secret: str | None,
    ) -> TokenResult:
        site = await self.site.get()
        if (
            site.library_owner_user_id != user.id
            or site.admin_locked_at is not None
            or user.role != UserRole.ADMIN
            or user.status != UserStatus.ACTIVE
            or passkey.user_id != user.id
            or passkey.revoked_at is not None
        ):
            raise self.invalid_credential()
        now = datetime.now(UTC)
        device, issued_device_secret = await self._admin_device(
            user=user,
            device_input=device_input,
            presented_secret=device_secret,
            client_ip=client_ip,
            user_agent=user_agent,
            now=now,
        )
        await self.auth.revoke_device_sessions(device.id, now=now, reason="explicit_passkey_login")
        result = await self._new_session(
            user=user,
            device=device,
            expires_at=now + timedelta(days=self.settings.auth_refresh_token_ttl_days),
            now=now,
            passkey_id=passkey.id,
            device_secret=issued_device_secret,
        )
        passkey.last_used_at = now
        passkey.updated_at = now
        user.last_login_at = now
        user.updated_at = now
        self.auth.audit(
            "passkey_login_succeeded",
            "success",
            actor_user_id=user.id,
            subject_user_id=user.id,
            session_id=result.context.session.id,
            device_id=device.id,
            passkey_id=passkey.id,
            client_ip=self._ip(client_ip),
            user_agent_summary=self._user_agent(user_agent),
        )
        return result

    async def upgrade_recovery_session(
        self, context: AuthContext, passkey: AdminPasskeyModel
    ) -> TokenResult:
        if not context.session.recovery_mode:
            raise ApplicationError(
                "recovery_session_required",
                "需要有效的管理员恢复会话。",
                status_code=HTTPStatus.FORBIDDEN,
            )
        now = datetime.now(UTC)
        revoked_count = await self.auth.revoke_user_sessions(
            context.user.id,
            now=now,
            reason="admin_recovery_completed",
        )
        site = await self.site.get(for_update=True)
        site.admin_locked_at = None
        site.updated_at = now
        result = await self._new_session(
            user=context.user,
            device=context.device,
            expires_at=now + timedelta(days=self.settings.auth_refresh_token_ttl_days),
            now=now,
            passkey_id=passkey.id,
            device_secret=None,
        )
        self.auth.audit(
            "admin_recovery_completed",
            "success",
            actor_user_id=context.user.id,
            subject_user_id=context.user.id,
            session_id=result.context.session.id,
            device_id=context.device.id,
            passkey_id=passkey.id,
            metadata={"revoked_old_sessions": revoked_count},
        )
        return result

    async def refresh(self, raw_refresh_token: str, device_secret: str | None) -> TokenResult:
        now = datetime.now(UTC)
        token_hash = self.tokens.hash_refresh_token(raw_refresh_token)
        refresh = await self.auth.refresh_for_update(token_hash)
        if refresh is None:
            raise ApplicationError(
                "invalid_refresh_token",
                "刷新凭据无效。",
                status_code=HTTPStatus.UNAUTHORIZED,
            )
        auth_session = await self.auth.get_session(refresh.session_id)
        if auth_session is None:
            raise ApplicationError(
                "invalid_refresh_token", "刷新凭据无效。", status_code=HTTPStatus.UNAUTHORIZED
            )
        if not await self._device_secret_matches(auth_session.device_id, device_secret):
            self.auth.audit(
                "refresh_device_binding_failed",
                "failure",
                subject_user_id=auth_session.user_id,
                session_id=auth_session.id,
                device_id=auth_session.device_id,
                access_credential_id=auth_session.access_credential_id,
                passkey_id=auth_session.passkey_id,
            )
            await self.session.commit()
            raise ApplicationError(
                "invalid_refresh_token",
                "刷新凭据无效。",
                status_code=HTTPStatus.UNAUTHORIZED,
            )
        if refresh.used_at is not None:
            await self.auth.revoke_session(auth_session, now=now, reason="refresh_reuse_detected")
            self.auth.audit(
                "refresh_reuse_detected",
                "failure",
                subject_user_id=auth_session.user_id,
                session_id=auth_session.id,
                device_id=auth_session.device_id,
                access_credential_id=auth_session.access_credential_id,
                passkey_id=auth_session.passkey_id,
            )
            await self.session.commit()
            raise ApplicationError(
                "refresh_token_reused",
                "检测到刷新凭据重放，会话已撤销。",
                status_code=HTTPStatus.UNAUTHORIZED,
            )
        if refresh.expires_at <= now:
            refresh.revoked_at = now
            await self.session.commit()
            raise ApplicationError(
                "refresh_token_expired", "刷新凭据已过期。", status_code=HTTPStatus.UNAUTHORIZED
            )
        if refresh.revoked_at is not None:
            raise ApplicationError(
                "invalid_refresh_token", "刷新凭据无效。", status_code=HTTPStatus.UNAUTHORIZED
            )
        context = await self.active_context(auth_session)
        refresh.used_at = now
        raw_replacement, replacement_hash = self.tokens.new_refresh_token()
        replacement = RefreshTokenModel(
            session_id=auth_session.id,
            token_hash=replacement_hash,
            issued_at=now,
            expires_at=auth_session.expires_at,
        )
        await self.auth.add(replacement)
        refresh.replaced_by_token_id = replacement.id
        auth_session.last_seen_at = now
        context.device.last_seen_at = now
        context.device.updated_at = now
        self.auth.audit(
            "refresh_succeeded",
            "success",
            actor_user_id=context.user.id,
            subject_user_id=context.user.id,
            session_id=auth_session.id,
            device_id=context.device.id,
            access_credential_id=auth_session.access_credential_id,
            passkey_id=auth_session.passkey_id,
        )
        access_token, expires_in = self.tokens.issue_access_token(
            user_id=context.user.id,
            session_id=auth_session.id,
            device_id=context.device.id,
            role=context.user.role.value,
            session_expires_at=auth_session.expires_at,
            now=now,
        )
        await self.session.commit()
        return TokenResult(
            access_token=access_token,
            expires_in=expires_in,
            refresh_token=raw_replacement,
            device_secret=None,
            context=context,
        )

    async def active_context(self, auth_session: AuthSessionModel) -> AuthContext:
        now = datetime.now(UTC)
        user = await self.users.get(auth_session.user_id)
        device = await self.session.get(DeviceModel, auth_session.device_id)
        if user is None or device is None or device.user_id != user.id:
            raise self.invalid_session()
        if user.status != UserStatus.ACTIVE:
            raise self.invalid_session()
        if auth_session.revoked_at is not None or auth_session.expires_at <= now:
            raise self.invalid_session()
        if device.revoked_at is not None:
            raise self.invalid_session()
        site = await self.site.get()
        if user.role == UserRole.ADMIN:
            if site.library_owner_user_id != user.id:
                raise self.invalid_session()
            if site.admin_locked_at is not None and not auth_session.recovery_mode:
                raise self.invalid_session()
            if auth_session.recovery_mode:
                if auth_session.recovery_credential_id is None:
                    raise self.invalid_session()
            else:
                if auth_session.passkey_id is None:
                    raise self.invalid_session()
                passkey = await self.session.get(AdminPasskeyModel, auth_session.passkey_id)
                if passkey is None or passkey.user_id != user.id or passkey.revoked_at is not None:
                    raise self.invalid_session()
        else:
            if auth_session.access_credential_id is None:
                raise self.invalid_session()
            credential = await self.session.get(
                ReaderAccessCredentialModel, auth_session.access_credential_id
            )
            if (
                credential is None
                or credential.user_id != user.id
                or credential.status != AccessCredentialStatus.ACTIVE
                or credential.expires_at <= now
                or device.access_credential_id != credential.id
            ):
                raise self.invalid_session()
        return AuthContext(user=user, device=device, session=auth_session)

    async def logout(self, context: AuthContext) -> None:
        now = datetime.now(UTC)
        await self.auth.revoke_session(context.session, now=now, reason="logout")
        self.auth.audit(
            "logout",
            "success",
            actor_user_id=context.user.id,
            subject_user_id=context.user.id,
            session_id=context.session.id,
            device_id=context.device.id,
            access_credential_id=context.session.access_credential_id,
            passkey_id=context.session.passkey_id,
        )
        await self.session.commit()

    async def revoke_session(self, context: AuthContext, session_id: UUID) -> bool:
        target = await self.auth.owned_session(context.user.id, session_id)
        if target is None:
            raise ApplicationError(
                "session_not_found", "会话不存在。", status_code=HTTPStatus.NOT_FOUND
            )
        await self.auth.revoke_session(target, now=datetime.now(UTC), reason="user_revoked")
        self.auth.audit(
            "session_revoked",
            "success",
            actor_user_id=context.user.id,
            subject_user_id=context.user.id,
            session_id=target.id,
            device_id=target.device_id,
            access_credential_id=target.access_credential_id,
            passkey_id=target.passkey_id,
        )
        await self.session.commit()
        return target.id == context.session.id

    async def revoke_other_sessions(self, context: AuthContext) -> int:
        count = await self.auth.revoke_other_sessions(
            context.user.id, context.session.id, now=datetime.now(UTC)
        )
        await self.session.commit()
        return count

    async def list_sessions(
        self, context: AuthContext
    ) -> list[tuple[AuthSessionModel, DeviceModel]]:
        return await self.auth.list_sessions(context.user.id)

    async def list_devices(self, context: AuthContext) -> list[tuple[DeviceModel, int]]:
        return await self.auth.list_devices(context.user.id)

    async def rename_device(self, context: AuthContext, device_id: UUID, name: str) -> DeviceModel:
        device = await self.auth.owned_device(context.user.id, device_id)
        if device is None:
            raise ApplicationError(
                "device_not_found", "设备不存在。", status_code=HTTPStatus.NOT_FOUND
            )
        device.name = self._device_name(name)
        device.updated_at = datetime.now(UTC)
        await self.session.commit()
        return device

    async def revoke_device(self, context: AuthContext, device_id: UUID) -> bool:
        device = await self.auth.owned_device(context.user.id, device_id)
        if device is None:
            raise ApplicationError(
                "device_not_found", "设备不存在。", status_code=HTTPStatus.NOT_FOUND
            )
        now = datetime.now(UTC)
        device.revoked_at = device.revoked_at or now
        device.updated_at = now
        await self.auth.revoke_device_sessions(device.id, now=now, reason="device_revoked")
        self.auth.audit(
            "device_revoked",
            "success",
            actor_user_id=context.user.id,
            subject_user_id=context.user.id,
            device_id=device.id,
            access_credential_id=device.access_credential_id,
        )
        await self.session.commit()
        return device.id == context.device.id

    async def _reader_login(
        self, credential: ReaderAccessCredentialModel, command: CredentialLogin, now: datetime
    ) -> TokenResult:
        user = await self.users.get(credential.user_id)
        if user is None:
            raise self.invalid_credential()
        device = await self._presented_device(
            command.device_secret,
            expected_user_id=user.id,
            expected_credential_id=credential.id,
        )
        issued_device_secret: str | None = None
        if device is None:
            if not credential.allow_new_devices:
                self.auth.audit(
                    "device_authorization_denied",
                    "failure",
                    subject_user_id=user.id,
                    access_credential_id=credential.id,
                    client_ip=self._ip(command.client_ip),
                    user_agent_summary=self._user_agent(command.user_agent),
                )
                await self.session.commit()
                raise self.invalid_credential()
            if await self.credentials.active_device_count(credential.id) >= credential.max_devices:
                self.auth.audit(
                    "device_limit_exceeded",
                    "failure",
                    subject_user_id=user.id,
                    access_credential_id=credential.id,
                    client_ip=self._ip(command.client_ip),
                    user_agent_summary=self._user_agent(command.user_agent),
                )
                await self.session.commit()
                raise ApplicationError(
                    "device_limit_reached",
                    "当前设备授权数量已达到上限，请联系管理员移除旧设备。",
                    status_code=HTTPStatus.CONFLICT,
                )
            issued_device_secret, secret_hash = self.tokens.new_device_secret()
            device = DeviceModel(
                user_id=user.id,
                access_credential_id=credential.id,
                client_instance_id=command.device.client_instance_id,
                device_secret_hash=secret_hash,
                name=self._device_name(command.device.name),
                platform=command.device.platform,
                app_version=command.device.app_version,
                first_authorized_ip=self._ip(command.client_ip),
                last_used_ip=self._ip(command.client_ip),
                user_agent_summary=self._user_agent(command.user_agent),
                first_seen_at=now,
                last_seen_at=now,
                created_at=now,
                updated_at=now,
            )
            await self.auth.add(device)
            self.auth.audit(
                "device_authorized",
                "success",
                actor_user_id=user.id,
                subject_user_id=user.id,
                device_id=device.id,
                access_credential_id=credential.id,
                client_ip=self._ip(command.client_ip),
                user_agent_summary=self._user_agent(command.user_agent),
            )
        else:
            self._touch_device(device, command.device, command.client_ip, command.user_agent, now)
        await self.auth.revoke_device_sessions(device.id, now=now, reason="explicit_login")
        credential.last_used_at = now
        credential.updated_at = now
        user.last_login_at = now
        user.updated_at = now
        result = await self._new_session(
            user=user,
            device=device,
            expires_at=min(
                credential.expires_at,
                now + timedelta(days=self.settings.auth_refresh_token_ttl_days),
            ),
            now=now,
            access_credential_id=credential.id,
            device_secret=issued_device_secret,
        )
        self.auth.audit(
            "login_succeeded",
            "success",
            actor_user_id=user.id,
            subject_user_id=user.id,
            session_id=result.context.session.id,
            device_id=device.id,
            access_credential_id=credential.id,
            client_ip=self._ip(command.client_ip),
            user_agent_summary=self._user_agent(command.user_agent),
        )
        return result

    async def _recovery_login(
        self, credential: AdminRecoveryCredentialModel, command: CredentialLogin, now: datetime
    ) -> TokenResult:
        user = await self.users.get(credential.user_id)
        site = await self.site.get()
        if (
            user is None
            or user.role != UserRole.ADMIN
            or user.status != UserStatus.ACTIVE
            or site.library_owner_user_id != user.id
        ):
            raise self.invalid_credential()
        credential.used_at = now
        device, issued_device_secret = await self._admin_device(
            user=user,
            device_input=command.device,
            presented_secret=command.device_secret,
            client_ip=command.client_ip,
            user_agent=command.user_agent,
            now=now,
        )
        await self.auth.revoke_device_sessions(device.id, now=now, reason="recovery_login")
        result = await self._new_session(
            user=user,
            device=device,
            expires_at=credential.expires_at,
            now=now,
            recovery_credential_id=credential.id,
            recovery_mode=True,
            device_secret=issued_device_secret,
        )
        self.auth.audit(
            "admin_recovery_used",
            "success",
            actor_user_id=user.id,
            subject_user_id=user.id,
            session_id=result.context.session.id,
            device_id=device.id,
            client_ip=self._ip(command.client_ip),
            user_agent_summary=self._user_agent(command.user_agent),
        )
        return result

    async def _new_session(
        self,
        *,
        user: UserModel,
        device: DeviceModel,
        expires_at: datetime,
        now: datetime,
        access_credential_id: UUID | None = None,
        passkey_id: UUID | None = None,
        recovery_credential_id: UUID | None = None,
        recovery_mode: bool = False,
        device_secret: str | None,
    ) -> TokenResult:
        auth_session = AuthSessionModel(
            user_id=user.id,
            device_id=device.id,
            access_credential_id=access_credential_id,
            passkey_id=passkey_id,
            recovery_credential_id=recovery_credential_id,
            recovery_mode=recovery_mode,
            created_at=now,
            last_seen_at=now,
            expires_at=expires_at,
        )
        await self.auth.add(auth_session)
        raw_refresh, token_hash = self.tokens.new_refresh_token()
        refresh = RefreshTokenModel(
            session_id=auth_session.id,
            token_hash=token_hash,
            issued_at=now,
            expires_at=expires_at,
        )
        await self.auth.add(refresh)
        access_token, expires_in = self.tokens.issue_access_token(
            user_id=user.id,
            session_id=auth_session.id,
            device_id=device.id,
            role=user.role.value,
            session_expires_at=expires_at,
            now=now,
        )
        return TokenResult(
            access_token=access_token,
            expires_in=expires_in,
            refresh_token=raw_refresh,
            device_secret=device_secret,
            context=AuthContext(user=user, device=device, session=auth_session),
        )

    async def _admin_device(
        self,
        *,
        user: UserModel,
        device_input: LoginDevice,
        presented_secret: str | None,
        client_ip: str,
        user_agent: str | None,
        now: datetime,
    ) -> tuple[DeviceModel, str | None]:
        device = await self._presented_device(
            presented_secret, expected_user_id=user.id, expected_credential_id=None
        )
        if device is not None:
            self._touch_device(device, device_input, client_ip, user_agent, now)
            return device, None
        raw_secret, secret_hash = self.tokens.new_device_secret()
        device = DeviceModel(
            user_id=user.id,
            access_credential_id=None,
            client_instance_id=device_input.client_instance_id,
            device_secret_hash=secret_hash,
            name=self._device_name(device_input.name),
            platform=device_input.platform,
            app_version=device_input.app_version,
            first_authorized_ip=self._ip(client_ip),
            last_used_ip=self._ip(client_ip),
            user_agent_summary=self._user_agent(user_agent),
            first_seen_at=now,
            last_seen_at=now,
            created_at=now,
            updated_at=now,
        )
        await self.auth.add(device)
        return device, raw_secret

    async def _presented_device(
        self,
        raw_secret: str | None,
        *,
        expected_user_id: UUID,
        expected_credential_id: UUID | None,
    ) -> DeviceModel | None:
        if not raw_secret:
            return None
        secret_hash = self.tokens.hash_device_secret(raw_secret)
        device = await self.credentials.device_by_secret_hash(secret_hash)
        if (
            device is None
            or device.user_id != expected_user_id
            or device.access_credential_id != expected_credential_id
            or device.revoked_at is not None
        ):
            return None
        return device

    async def _device_secret_matches(self, device_id: UUID, raw_secret: str | None) -> bool:
        if not raw_secret:
            return False
        device = await self.session.get(DeviceModel, device_id)
        if device is None or device.revoked_at is not None or not device.device_secret_hash:
            return False
        presented_hash = self.tokens.hash_device_secret(raw_secret)
        return hmac.compare_digest(device.device_secret_hash, presented_hash)

    async def _reader_credential_valid(
        self, credential: ReaderAccessCredentialModel, now: datetime
    ) -> bool:
        if credential.status != AccessCredentialStatus.ACTIVE or credential.expires_at <= now:
            return False
        user = await self.users.get(credential.user_id)
        site = await self.site.get()
        return bool(
            user is not None
            and user.role == UserRole.MEMBER
            and user.status == UserStatus.ACTIVE
            and site.library_owner_user_id is not None
            and site.migration_completed_at is not None
        )

    async def _recovery_credential_valid(
        self, credential: AdminRecoveryCredentialModel, now: datetime
    ) -> bool:
        return bool(
            credential.used_at is None
            and credential.revoked_at is None
            and credential.expires_at > now
        )

    async def _record_login_failure(
        self,
        keys: list[str],
        throttles: list[LoginThrottleModel | None],
        now: datetime,
    ) -> bool:
        blocked = False
        window = timedelta(seconds=self.settings.auth_login_window_seconds)
        for key, throttle in zip(keys, throttles, strict=True):
            if throttle is None:
                throttle = LoginThrottleModel(
                    key_hash=key,
                    failure_count=1,
                    window_started_at=now,
                    updated_at=now,
                )
                self.session.add(throttle)
            elif now - throttle.window_started_at >= window:
                throttle.failure_count = 1
                throttle.window_started_at = now
                throttle.blocked_until = None
                throttle.updated_at = now
            else:
                throttle.failure_count += 1
                throttle.updated_at = now
            if throttle.failure_count >= self.settings.auth_login_max_failures:
                throttle.blocked_until = now + timedelta(
                    seconds=self.settings.auth_login_block_seconds
                )
                blocked = True
        return blocked

    @staticmethod
    def _touch_device(
        device: DeviceModel,
        device_input: LoginDevice,
        client_ip: str,
        user_agent: str | None,
        now: datetime,
    ) -> None:
        device.name = AuthService._device_name(device_input.name)
        device.platform = device_input.platform
        device.app_version = device_input.app_version
        device.last_used_ip = AuthService._ip(client_ip)
        device.user_agent_summary = AuthService._user_agent(user_agent)
        device.last_seen_at = now
        device.updated_at = now

    @staticmethod
    def _device_name(name: str) -> str:
        normalized = name.strip()
        if not 1 <= len(normalized) <= 100:
            raise ApplicationError("validation_error", "设备名称长度必须为 1 到 100 个字符。")
        return normalized

    @staticmethod
    def _ip(value: str) -> str:
        return value.strip()[:64] or "unknown"

    @staticmethod
    def _user_agent(value: str | None) -> str | None:
        if not value:
            return None
        return " ".join(value.split())[:255]

    @staticmethod
    def invalid_credential() -> ApplicationError:
        return ApplicationError(
            "invalid_access_credential",
            GENERIC_CREDENTIAL_ERROR,
            status_code=HTTPStatus.UNAUTHORIZED,
        )

    @staticmethod
    def invalid_session() -> ApplicationError:
        return ApplicationError(
            "session_revoked",
            "会话已失效。",
            status_code=HTTPStatus.UNAUTHORIZED,
            headers={"WWW-Authenticate": "Bearer"},
        )
