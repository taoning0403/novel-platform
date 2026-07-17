from enum import StrEnum


class UserRole(StrEnum):
    ADMIN = "admin"
    MEMBER = "member"


class UserStatus(StrEnum):
    PENDING_SETUP = "pending_setup"
    ACTIVE = "active"
    DISABLED = "disabled"


class AccessCredentialStatus(StrEnum):
    ACTIVE = "active"
    SUSPENDED = "suspended"
    REVOKED = "revoked"


class AdminRecoveryPurpose(StrEnum):
    INITIALIZE = "initialize"
    RECOVERY = "recovery"
    CREDENTIAL_RESET = "credential_reset"


class WebAuthnChallengePurpose(StrEnum):
    REGISTRATION = "registration"
    AUTHENTICATION = "authentication"


class DevicePlatform(StrEnum):
    WEB = "web"
    WINDOWS = "windows"
    MACOS = "macos"
    LINUX = "linux"
    ANDROID = "android"
    IPADOS = "ipados"
    UNKNOWN = "unknown"
