from http import HTTPStatus
from uuid import UUID

from fastapi import APIRouter, Request, Response, status

from novel_platform.api.dependencies.auth import CurrentAdmin, CurrentAuth, LogoutAuth, PasskeyAdmin
from novel_platform.api.dependencies.database import DatabaseSession
from novel_platform.api.schemas import (
    CredentialLoginRequest,
    MeResponse,
    PasskeyAuthenticationRequest,
    PasskeyPatch,
    PasskeyRegistrationRequest,
    PasskeyRegistrationResponse,
    PasskeyResponse,
    RefreshRequest,
    RevokeOthersResponse,
    SessionResponse,
    TokenResponse,
    WebAuthnOptionsResponse,
)
from novel_platform.api.serializers import (
    me_response,
    passkey_response,
    session_response,
    token_response,
)
from novel_platform.application.auth.commands import (
    CredentialLogin,
    LoginDevice,
    PasskeyLogin,
)
from novel_platform.application.auth.service import AuthService
from novel_platform.application.auth.webauthn_service import WebAuthnService
from novel_platform.application.errors import ApplicationError
from novel_platform.config import Settings, get_settings

router = APIRouter(prefix="/auth", tags=["authentication"])


def set_refresh_cookie(response: Response, token: str, settings: Settings) -> None:
    response.set_cookie(
        key=settings.auth_cookie_name,
        value=token,
        max_age=settings.auth_refresh_token_ttl_days * 86_400,
        httponly=True,
        secure=settings.auth_cookie_secure,
        samesite=settings.auth_cookie_samesite,
        domain=settings.auth_cookie_domain,
        path="/api/v1/auth",
    )


def set_device_cookie(response: Response, token: str, settings: Settings) -> None:
    response.set_cookie(
        key=settings.auth_device_cookie_name,
        value=token,
        max_age=settings.auth_device_cookie_ttl_days * 86_400,
        httponly=True,
        secure=settings.auth_cookie_secure,
        samesite=settings.auth_cookie_samesite,
        domain=settings.auth_cookie_domain,
        path="/api/v1/auth",
    )


def clear_refresh_cookie(response: Response, settings: Settings) -> None:
    response.delete_cookie(
        key=settings.auth_cookie_name,
        httponly=True,
        secure=settings.auth_cookie_secure,
        samesite=settings.auth_cookie_samesite,
        domain=settings.auth_cookie_domain,
        path="/api/v1/auth",
    )


def clear_device_cookie(response: Response, settings: Settings) -> None:
    response.delete_cookie(
        key=settings.auth_device_cookie_name,
        httponly=True,
        secure=settings.auth_cookie_secure,
        samesite=settings.auth_cookie_samesite,
        domain=settings.auth_cookie_domain,
        path="/api/v1/auth",
    )


def client_ip(request: Request, settings: Settings) -> str:
    if settings.trust_proxy_headers:
        forwarded_for = request.headers.get("x-forwarded-for")
        if forwarded_for:
            return forwarded_for.split(",", maxsplit=1)[0].strip()
        forwarded = request.headers.get("forwarded")
        if forwarded:
            first = forwarded.split(",", maxsplit=1)[0]
            for part in first.split(";"):
                if part.strip().lower().startswith("for="):
                    return part.split("=", maxsplit=1)[1].strip().strip('"')
    return request.client.host if request.client is not None else "unknown"


def validate_cookie_origin(request: Request, settings: Settings) -> None:
    origin = request.headers.get("origin")
    if origin is None or origin.rstrip("/") not in {
        allowed.rstrip("/") for allowed in settings.cors_origins
    }:
        raise ApplicationError(
            "permission_denied",
            "请求来源不受信任。",
            status_code=HTTPStatus.FORBIDDEN,
        )


def webauthn_origin(request: Request) -> str:
    origin = request.headers.get("origin")
    if not origin:
        raise ApplicationError(
            "permission_denied", "安全设备请求缺少 Origin。", status_code=HTTPStatus.FORBIDDEN
        )
    return origin


def login_device(payload: CredentialLoginRequest | PasskeyAuthenticationRequest) -> LoginDevice:
    return LoginDevice(
        client_instance_id=payload.device.client_instance_id,
        name=payload.device.name,
        platform=payload.device.platform,
        app_version=payload.device.app_version,
    )


def apply_device_cookie(
    response: Response,
    issued_secret: str | None,
    presented_secret: str | None,
    settings: Settings,
) -> None:
    if issued_secret is not None:
        set_device_cookie(response, issued_secret, settings)
    elif presented_secret:
        # A successful login that reuses an already-authorized device renews the
        # independent device-cookie lifetime by re-issuing the presented secret.
        set_device_cookie(response, presented_secret, settings)


def apply_login_cookies(
    response: Response,
    result_token: str,
    device_secret: str | None,
    presented_device_secret: str | None,
    settings: Settings,
) -> None:
    set_refresh_cookie(response, result_token, settings)
    apply_device_cookie(response, device_secret, presented_device_secret, settings)
    response.headers["Cache-Control"] = "no-store"


@router.post("/login", response_model=TokenResponse, response_model_exclude_none=True)
async def login(
    payload: CredentialLoginRequest,
    request: Request,
    response: Response,
    session: DatabaseSession,
) -> TokenResponse:
    settings = get_settings()
    presented_device_secret = request.cookies.get(settings.auth_device_cookie_name)
    result = await AuthService(session, settings).credential_login(
        CredentialLogin(
            credential=payload.credential,
            device=login_device(payload),
            client_ip=client_ip(request, settings),
            user_agent=request.headers.get("user-agent"),
            device_secret=presented_device_secret,
        )
    )
    cookie_delivery = payload.refresh_token_delivery == "cookie"
    if cookie_delivery:
        apply_login_cookies(
            response,
            result.refresh_token,
            result.device_secret,
            presented_device_secret,
            settings,
        )
    else:
        apply_device_cookie(response, result.device_secret, presented_device_secret, settings)
    response.headers["Cache-Control"] = "no-store"
    return token_response(result, include_refresh=not cookie_delivery)


@router.post("/passkeys/authentication/options", response_model=WebAuthnOptionsResponse)
async def passkey_authentication_options(
    request: Request, response: Response, session: DatabaseSession
) -> WebAuthnOptionsResponse:
    result = await WebAuthnService(session, get_settings()).authentication_options(
        origin=webauthn_origin(request)
    )
    response.headers["Cache-Control"] = "no-store"
    return WebAuthnOptionsResponse(challenge_id=result.challenge_id, options=result.options)


@router.post(
    "/passkeys/authentication/verify",
    response_model=TokenResponse,
    response_model_exclude_none=True,
)
async def passkey_authentication_verify(
    payload: PasskeyAuthenticationRequest,
    request: Request,
    response: Response,
    session: DatabaseSession,
) -> TokenResponse:
    settings = get_settings()
    presented_device_secret = request.cookies.get(settings.auth_device_cookie_name)
    result = await WebAuthnService(session, settings).verify_authentication(
        PasskeyLogin(
            challenge_id=payload.challenge_id,
            credential=payload.credential,
            device=login_device(payload),
            client_ip=client_ip(request, settings),
            user_agent=request.headers.get("user-agent"),
            device_secret=presented_device_secret,
        ),
        origin=webauthn_origin(request),
    )
    cookie_delivery = payload.refresh_token_delivery == "cookie"
    if cookie_delivery:
        apply_login_cookies(
            response,
            result.refresh_token,
            result.device_secret,
            presented_device_secret,
            settings,
        )
    else:
        apply_device_cookie(response, result.device_secret, presented_device_secret, settings)
    response.headers["Cache-Control"] = "no-store"
    return token_response(result, include_refresh=not cookie_delivery)


@router.post("/passkeys/registration/options", response_model=WebAuthnOptionsResponse)
async def passkey_registration_options(
    request: Request,
    response: Response,
    session: DatabaseSession,
    current: PasskeyAdmin,
) -> WebAuthnOptionsResponse:
    result = await WebAuthnService(session, get_settings()).registration_options(
        current, origin=webauthn_origin(request)
    )
    response.headers["Cache-Control"] = "no-store"
    return WebAuthnOptionsResponse(challenge_id=result.challenge_id, options=result.options)


@router.post("/passkeys/registration/verify", response_model=PasskeyRegistrationResponse)
async def passkey_registration_verify(
    payload: PasskeyRegistrationRequest,
    request: Request,
    response: Response,
    session: DatabaseSession,
    current: PasskeyAdmin,
) -> PasskeyRegistrationResponse:
    settings = get_settings()
    result = await WebAuthnService(session, settings).verify_registration(
        current,
        challenge_id=payload.challenge_id,
        credential=payload.credential,
        name=payload.name,
        origin=webauthn_origin(request),
    )
    authentication = None
    if result.token_result is not None:
        set_refresh_cookie(response, result.token_result.refresh_token, settings)
        authentication = token_response(result.token_result, include_refresh=False)
    response.headers["Cache-Control"] = "no-store"
    return PasskeyRegistrationResponse(
        passkey=passkey_response(result.passkey), authentication=authentication
    )


@router.get("/passkeys", response_model=list[PasskeyResponse])
async def list_passkeys(session: DatabaseSession, current: CurrentAdmin) -> list[PasskeyResponse]:
    rows = await WebAuthnService(session, get_settings()).list_passkeys(current)
    return [passkey_response(row) for row in rows]


@router.patch("/passkeys/{passkey_id}", response_model=PasskeyResponse)
async def rename_passkey(
    passkey_id: UUID,
    payload: PasskeyPatch,
    session: DatabaseSession,
    current: CurrentAdmin,
) -> PasskeyResponse:
    row = await WebAuthnService(session, get_settings()).rename_passkey(
        current, passkey_id, payload.name
    )
    return passkey_response(row)


@router.delete("/passkeys/{passkey_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_passkey(passkey_id: UUID, session: DatabaseSession, current: CurrentAdmin) -> None:
    await WebAuthnService(session, get_settings()).revoke_passkey(current, passkey_id)


@router.post("/refresh", response_model=TokenResponse, response_model_exclude_none=True)
async def refresh(
    request: Request,
    response: Response,
    session: DatabaseSession,
    payload: RefreshRequest | None = None,
) -> TokenResponse:
    settings = get_settings()
    if payload is not None:
        body_delivery = True
        raw_token = payload.refresh_token
    else:
        body_delivery = False
        validate_cookie_origin(request, settings)
        raw_token = request.cookies.get(settings.auth_cookie_name, "")
    if not raw_token:
        clear_refresh_cookie(response, settings)
        raise ApplicationError(
            "invalid_refresh_token", "刷新凭据无效。", status_code=HTTPStatus.UNAUTHORIZED
        )
    result = await AuthService(session, settings).refresh(
        raw_token, request.cookies.get(settings.auth_device_cookie_name)
    )
    if not body_delivery:
        set_refresh_cookie(response, result.refresh_token, settings)
    response.headers["Cache-Control"] = "no-store"
    return token_response(result, include_refresh=body_delivery)


@router.get("/me", response_model=MeResponse)
async def me(current: CurrentAuth) -> MeResponse:
    return me_response(current)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(response: Response, session: DatabaseSession, current: LogoutAuth) -> None:
    settings = get_settings()
    await AuthService(session, settings).logout(current)
    clear_refresh_cookie(response, settings)


@router.get("/sessions", response_model=list[SessionResponse])
async def list_sessions(session: DatabaseSession, current: CurrentAuth) -> list[SessionResponse]:
    rows = await AuthService(session, get_settings()).list_sessions(current)
    return [
        session_response(auth_session, device, current_session_id=current.session.id)
        for auth_session, device in rows
    ]


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_session(
    session_id: UUID,
    response: Response,
    session: DatabaseSession,
    current: CurrentAuth,
) -> None:
    settings = get_settings()
    revoked_current = await AuthService(session, settings).revoke_session(current, session_id)
    if revoked_current:
        clear_refresh_cookie(response, settings)


@router.post("/sessions/revoke-others", response_model=RevokeOthersResponse)
async def revoke_other_sessions(
    session: DatabaseSession, current: CurrentAuth
) -> RevokeOthersResponse:
    count = await AuthService(session, get_settings()).revoke_other_sessions(current)
    return RevokeOthersResponse(revoked_count=count)
