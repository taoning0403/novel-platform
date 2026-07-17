import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import jwt

from novel_platform.application.errors import ApplicationError
from novel_platform.config import Settings


@dataclass(frozen=True, slots=True)
class AccessTokenClaims:
    user_id: UUID
    session_id: UUID
    device_id: UUID
    role: str


class TokenService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.jwt_secret = settings.auth_jwt_secret.get_secret_value()
        self.hash_secret = settings.auth_hash_secret.get_secret_value().encode()
        self.credential_hash_secret = (
            settings.auth_credential_hash_secret.get_secret_value().encode()
        )

    def issue_access_token(
        self,
        *,
        user_id: UUID,
        session_id: UUID,
        device_id: UUID,
        role: str,
        session_expires_at: datetime | None = None,
        now: datetime | None = None,
    ) -> tuple[str, int]:
        issued_at = now or datetime.now(UTC)
        ttl = self.settings.auth_access_token_ttl_seconds
        expires_at = issued_at + timedelta(seconds=ttl)
        if session_expires_at is not None:
            expires_at = min(expires_at, session_expires_at)
        expires_in = max(1, int((expires_at - issued_at).total_seconds()))
        payload = {
            "sub": str(user_id),
            "sid": str(session_id),
            "did": str(device_id),
            "role": role,
            "iss": self.settings.auth_issuer,
            "aud": self.settings.auth_audience,
            "iat": issued_at,
            "exp": expires_at,
            "jti": str(uuid4()),
        }
        return jwt.encode(payload, self.jwt_secret, algorithm="HS256"), expires_in

    def decode_access_token(self, token: str) -> AccessTokenClaims:
        try:
            payload = jwt.decode(
                token,
                self.jwt_secret,
                algorithms=["HS256"],
                audience=self.settings.auth_audience,
                issuer=self.settings.auth_issuer,
                options={
                    "require": ["sub", "sid", "did", "role", "iss", "aud", "iat", "exp", "jti"]
                },
            )
            return AccessTokenClaims(
                user_id=UUID(payload["sub"]),
                session_id=UUID(payload["sid"]),
                device_id=UUID(payload["did"]),
                role=str(payload["role"]),
            )
        except jwt.ExpiredSignatureError as exc:
            raise ApplicationError(
                "access_token_expired",
                "访问令牌已过期。",
                status_code=401,
                headers={"WWW-Authenticate": "Bearer"},
            ) from exc
        except (jwt.InvalidTokenError, KeyError, TypeError, ValueError) as exc:
            raise ApplicationError(
                "invalid_access_token",
                "访问令牌无效。",
                status_code=401,
                headers={"WWW-Authenticate": "Bearer"},
            ) from exc

    def new_refresh_token(self) -> tuple[str, str]:
        token = secrets.token_urlsafe(48)
        return token, self.hash_refresh_token(token)

    def hash_refresh_token(self, token: str) -> str:
        return hmac.new(self.hash_secret, token.encode(), hashlib.sha256).hexdigest()

    def new_access_credential(self) -> tuple[str, str, str]:
        raw = f"npa_{secrets.token_urlsafe(32)}"
        return raw, self.hash_access_credential(raw), self.credential_hint(raw)

    def new_recovery_credential(self) -> tuple[str, str, str]:
        raw = f"npa_{secrets.token_urlsafe(32)}"
        return raw, self.hash_recovery_credential(raw), self.credential_hint(raw)

    def new_device_secret(self) -> tuple[str, str]:
        raw = secrets.token_urlsafe(32)
        return raw, self.hash_device_secret(raw)

    def hash_access_credential(self, token: str) -> str:
        return self._domain_hash("reader-access", token)

    def hash_recovery_credential(self, token: str) -> str:
        return self._domain_hash("admin-recovery", token)

    def hash_device_secret(self, token: str) -> str:
        return self._domain_hash("device-authorization", token)

    def credential_hint(self, token: str) -> str:
        return f"npa_••••{token[-6:]}"

    def hash_login_ip(self, client_ip: str) -> str:
        return self._domain_hash("login-ip", client_ip)

    def hash_login_credential(self, credential_hash: str) -> str:
        return self._domain_hash("login-credential", credential_hash)

    def _domain_hash(self, purpose: str, value: str) -> str:
        message = f"novel-platform:v0.5:{purpose}\0{value}".encode()
        return hmac.new(self.credential_hash_secret, message, hashlib.sha256).hexdigest()

    def hash_login_key(self, normalized_username: str, client_ip: str) -> str:
        value = f"{normalized_username}\0{client_ip}".encode()
        return hmac.new(self.hash_secret, value, hashlib.sha256).hexdigest()
