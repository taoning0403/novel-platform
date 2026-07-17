import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from http import HTTPStatus
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from webauthn import (
    generate_authentication_options,
    generate_registration_options,
    options_to_json,
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.helpers import base64url_to_bytes
from webauthn.helpers.exceptions import (
    InvalidAuthenticationResponse,
    InvalidRegistrationResponse,
)
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

from novel_platform.application.auth.commands import PasskeyLogin
from novel_platform.application.auth.context import AuthContext, TokenResult
from novel_platform.application.auth.service import AuthService
from novel_platform.application.errors import ApplicationError
from novel_platform.config import Settings
from novel_platform.domain.auth.models import UserRole, UserStatus, WebAuthnChallengePurpose
from novel_platform.infrastructure.database.models import (
    AdminPasskeyModel,
    UserModel,
    WebAuthnChallengeModel,
)
from novel_platform.infrastructure.repositories.auth import AuthRepository
from novel_platform.infrastructure.repositories.credentials import CredentialRepository
from novel_platform.infrastructure.repositories.site import SiteRepository


@dataclass(frozen=True, slots=True)
class WebAuthnOptions:
    challenge_id: UUID
    options: dict[str, Any]


@dataclass(frozen=True, slots=True)
class RegistrationResult:
    passkey: AdminPasskeyModel
    token_result: TokenResult | None


class WebAuthnService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self.settings = settings
        self.credentials = CredentialRepository(session)
        self.site = SiteRepository(session)
        self.auth = AuthRepository(session)
        self.sessions = AuthService(session, settings)

    async def registration_options(self, context: AuthContext, *, origin: str) -> WebAuthnOptions:
        self._require_admin_context(context)
        expected_origin = self._origin(origin)
        passkeys = await self.credentials.list_passkeys(context.user.id)
        options = generate_registration_options(
            rp_id=self.settings.webauthn_rp_id,
            rp_name=self.settings.webauthn_rp_name,
            user_name="site-administrator",
            user_id=context.user.id.bytes,
            user_display_name=context.user.display_name,
            timeout=self.settings.webauthn_challenge_ttl_seconds * 1000,
            authenticator_selection=AuthenticatorSelectionCriteria(
                resident_key=ResidentKeyRequirement.REQUIRED,
                require_resident_key=True,
                user_verification=UserVerificationRequirement.REQUIRED,
            ),
            exclude_credentials=[
                PublicKeyCredentialDescriptor(id=passkey.credential_id)
                for passkey in passkeys
                if passkey.revoked_at is None
            ],
        )
        challenge = await self._store_challenge(
            challenge=options.challenge,
            purpose=WebAuthnChallengePurpose.REGISTRATION,
            user=context.user,
            origin=expected_origin,
        )
        await self.session.commit()
        return WebAuthnOptions(challenge.id, json.loads(options_to_json(options)))

    async def verify_registration(
        self,
        context: AuthContext,
        *,
        challenge_id: UUID,
        credential: dict[str, Any],
        name: str,
        origin: str,
    ) -> RegistrationResult:
        self._require_admin_context(context)
        try:
            challenge = await self._challenge(
                challenge_id,
                WebAuthnChallengePurpose.REGISTRATION,
                context.user,
                origin,
            )
        except ApplicationError:
            self.auth.audit(
                "passkey_registration_failed",
                "failure",
                actor_user_id=context.user.id,
                subject_user_id=context.user.id,
                session_id=context.session.id,
                device_id=context.device.id,
            )
            await self.session.commit()
            raise
        now = datetime.now(UTC)
        challenge.used_at = now
        try:
            verification = verify_registration_response(
                credential=credential,
                expected_challenge=challenge.challenge,
                expected_rp_id=challenge.rp_id,
                expected_origin=challenge.expected_origin,
                require_user_verification=True,
            )
        except InvalidRegistrationResponse as exc:
            self.auth.audit(
                "passkey_registration_failed",
                "failure",
                actor_user_id=context.user.id,
                subject_user_id=context.user.id,
                session_id=context.session.id,
                device_id=context.device.id,
            )
            await self.session.commit()
            raise ApplicationError(
                "invalid_passkey_response",
                "安全设备注册验证失败。",
                status_code=HTTPStatus.UNAUTHORIZED,
            ) from exc
        existing = await self.credentials.passkey_by_credential_id(verification.credential_id)
        if existing is not None:
            await self.session.commit()
            raise ApplicationError(
                "passkey_already_registered",
                "该安全设备已经注册。",
                status_code=HTTPStatus.CONFLICT,
            )
        normalized_name = self._passkey_name(name)
        transports = self._transports(credential)
        passkey = AdminPasskeyModel(
            user_id=context.user.id,
            credential_id=verification.credential_id,
            public_key=verification.credential_public_key,
            sign_count=verification.sign_count,
            name=normalized_name,
            transports=transports,
            device_type=verification.credential_device_type.value,
            backed_up=verification.credential_backed_up,
            created_at=now,
            updated_at=now,
        )
        self.session.add(passkey)
        await self.session.flush()
        token_result = None
        if context.session.recovery_mode:
            token_result = await self.sessions.upgrade_recovery_session(context, passkey)
        self.auth.audit(
            "passkey_registered",
            "success",
            actor_user_id=context.user.id,
            subject_user_id=context.user.id,
            session_id=context.session.id,
            device_id=context.device.id,
            passkey_id=passkey.id,
        )
        await self.session.commit()
        return RegistrationResult(passkey, token_result)

    async def authentication_options(self, *, origin: str) -> WebAuthnOptions:
        expected_origin = self._origin(origin)
        site = await self.site.get()
        user = (
            await self.session.get(UserModel, site.library_owner_user_id)
            if site.library_owner_user_id is not None
            else None
        )
        if user is None:
            user = (
                await self.session.scalars(
                    select(UserModel).order_by(UserModel.created_at).limit(1)
                )
            ).one()
        options = generate_authentication_options(
            rp_id=self.settings.webauthn_rp_id,
            timeout=self.settings.webauthn_challenge_ttl_seconds * 1000,
            allow_credentials=None,
            user_verification=UserVerificationRequirement.REQUIRED,
        )
        challenge = await self._store_challenge(
            challenge=options.challenge,
            purpose=WebAuthnChallengePurpose.AUTHENTICATION,
            user=user,
            origin=expected_origin,
        )
        await self.session.commit()
        return WebAuthnOptions(challenge.id, json.loads(options_to_json(options)))

    async def verify_authentication(self, command: PasskeyLogin, *, origin: str) -> TokenResult:
        credential_id = self._credential_id(command.credential)
        passkey = await self.credentials.passkey_by_credential_id(credential_id, for_update=True)
        if passkey is None or passkey.revoked_at is not None:
            self.auth.audit(
                "passkey_authentication_failed",
                "failure",
                client_ip=AuthService._ip(command.client_ip),
                user_agent_summary=AuthService._user_agent(command.user_agent),
            )
            await self.session.commit()
            raise AuthService.invalid_credential()
        user = await self.session.get(UserModel, passkey.user_id)
        if user is None:
            self.auth.audit(
                "passkey_authentication_failed",
                "failure",
                passkey_id=passkey.id,
                client_ip=AuthService._ip(command.client_ip),
                user_agent_summary=AuthService._user_agent(command.user_agent),
            )
            await self.session.commit()
            raise AuthService.invalid_credential()
        try:
            challenge = await self._challenge(
                command.challenge_id,
                WebAuthnChallengePurpose.AUTHENTICATION,
                user,
                origin,
            )
        except ApplicationError:
            self.auth.audit(
                "passkey_authentication_failed",
                "failure",
                subject_user_id=user.id,
                passkey_id=passkey.id,
                client_ip=AuthService._ip(command.client_ip),
                user_agent_summary=AuthService._user_agent(command.user_agent),
            )
            await self.session.commit()
            raise
        now = datetime.now(UTC)
        challenge.used_at = now
        try:
            verification = verify_authentication_response(
                credential=command.credential,
                expected_challenge=challenge.challenge,
                expected_rp_id=challenge.rp_id,
                expected_origin=challenge.expected_origin,
                credential_public_key=passkey.public_key,
                credential_current_sign_count=passkey.sign_count,
                require_user_verification=True,
            )
        except InvalidAuthenticationResponse as exc:
            self.auth.audit(
                "passkey_authentication_failed",
                "failure",
                subject_user_id=user.id,
                passkey_id=passkey.id,
                client_ip=AuthService._ip(command.client_ip),
                user_agent_summary=AuthService._user_agent(command.user_agent),
            )
            await self.session.commit()
            raise AuthService.invalid_credential() from exc
        passkey.sign_count = verification.new_sign_count
        passkey.device_type = verification.credential_device_type.value
        passkey.backed_up = verification.credential_backed_up
        result = await self.sessions.create_passkey_session(
            user=user,
            passkey=passkey,
            device_input=command.device,
            client_ip=command.client_ip,
            user_agent=command.user_agent,
            device_secret=command.device_secret,
        )
        await self.session.commit()
        return result

    async def list_passkeys(self, context: AuthContext) -> list[AdminPasskeyModel]:
        self._require_admin_context(context)
        return await self.credentials.list_passkeys(context.user.id)

    async def rename_passkey(
        self, context: AuthContext, passkey_id: UUID, name: str
    ) -> AdminPasskeyModel:
        self._require_admin_context(context)
        passkey = await self.credentials.passkey(context.user.id, passkey_id)
        if passkey is None:
            raise ApplicationError(
                "passkey_not_found", "安全设备不存在。", status_code=HTTPStatus.NOT_FOUND
            )
        passkey.name = self._passkey_name(name)
        passkey.updated_at = datetime.now(UTC)
        self.auth.audit(
            "passkey_renamed",
            "success",
            actor_user_id=context.user.id,
            subject_user_id=context.user.id,
            passkey_id=passkey.id,
        )
        await self.session.commit()
        return passkey

    async def revoke_passkey(self, context: AuthContext, passkey_id: UUID) -> None:
        self._require_admin_context(context)
        passkey = await self.credentials.passkey(context.user.id, passkey_id)
        if passkey is None:
            raise ApplicationError(
                "passkey_not_found", "安全设备不存在。", status_code=HTTPStatus.NOT_FOUND
            )
        if passkey.revoked_at is not None:
            return
        if await self.credentials.active_passkey_count(context.user.id) <= 1:
            raise ApplicationError(
                "cannot_revoke_last_passkey",
                "不能撤销最后一个安全设备;请先注册另一枚 Passkey 或使用服务器恢复流程。",
                status_code=HTTPStatus.CONFLICT,
            )
        now = datetime.now(UTC)
        passkey.revoked_at = now
        passkey.updated_at = now
        await self.auth.revoke_passkey_sessions(passkey.id, now=now, reason="passkey_revoked")
        self.auth.audit(
            "passkey_revoked",
            "success",
            actor_user_id=context.user.id,
            subject_user_id=context.user.id,
            passkey_id=passkey.id,
        )
        await self.session.commit()

    async def _store_challenge(
        self,
        *,
        challenge: bytes,
        purpose: WebAuthnChallengePurpose,
        user: UserModel,
        origin: str,
    ) -> WebAuthnChallengeModel:
        now = datetime.now(UTC)
        await self.credentials.delete_expired_challenges(now=now)
        row = WebAuthnChallengeModel(
            challenge=challenge,
            purpose=purpose,
            user_id=user.id,
            expected_origin=origin,
            rp_id=self.settings.webauthn_rp_id,
            expires_at=now + timedelta(seconds=self.settings.webauthn_challenge_ttl_seconds),
            created_at=now,
        )
        self.session.add(row)
        await self.session.flush()
        return row

    async def _challenge(
        self,
        challenge_id: UUID,
        purpose: WebAuthnChallengePurpose,
        user: UserModel,
        origin: str,
    ) -> WebAuthnChallengeModel:
        challenge = await self.credentials.challenge_for_update(challenge_id, purpose)
        now = datetime.now(UTC)
        if (
            challenge is None
            or challenge.user_id != user.id
            or challenge.used_at is not None
            or challenge.expires_at <= now
            or challenge.rp_id != self.settings.webauthn_rp_id
            or challenge.expected_origin != self._origin(origin)
        ):
            raise ApplicationError(
                "invalid_webauthn_challenge",
                "安全设备验证请求无效或已过期。",
                status_code=HTTPStatus.UNAUTHORIZED,
            )
        return challenge

    def _origin(self, origin: str) -> str:
        normalized = origin.rstrip("/")
        allowed = {value.rstrip("/") for value in self.settings.webauthn_origins}
        if normalized not in allowed:
            raise ApplicationError(
                "permission_denied", "请求来源不受信任。", status_code=HTTPStatus.FORBIDDEN
            )
        return normalized

    @staticmethod
    def _credential_id(credential: dict[str, Any]) -> bytes:
        value = credential.get("rawId") or credential.get("id")
        if not isinstance(value, str):
            raise AuthService.invalid_credential()
        try:
            return base64url_to_bytes(value)
        except ValueError as exc:
            raise AuthService.invalid_credential() from exc

    @staticmethod
    def _transports(credential: dict[str, Any]) -> list[str]:
        response = credential.get("response")
        if not isinstance(response, dict):
            return []
        transports = response.get("transports")
        if not isinstance(transports, list):
            return []
        return [str(value)[:30] for value in transports if isinstance(value, str)][:10]

    @staticmethod
    def _passkey_name(name: str) -> str:
        normalized = name.strip()
        if not 1 <= len(normalized) <= 100:
            raise ApplicationError("validation_error", "安全设备名称长度必须为 1 到 100。")
        return normalized

    @staticmethod
    def _require_admin_context(context: AuthContext) -> None:
        if context.user.role != UserRole.ADMIN or context.user.status != UserStatus.ACTIVE:
            raise ApplicationError(
                "admin_required", "需要管理员权限。", status_code=HTTPStatus.FORBIDDEN
            )
