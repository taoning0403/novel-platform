from fastapi import Response

from novel_platform.api.routes.auth import apply_device_cookie
from novel_platform.config import Settings


def test_apply_device_cookie_prefers_newly_issued_secret() -> None:
    response = Response()
    apply_device_cookie(response, "issued-secret", "presented-secret", Settings())
    header = response.headers["set-cookie"]
    assert "novel_device=issued-secret" in header
    assert f"Max-Age={365 * 86_400}" in header
    assert "HttpOnly" in header
    assert "Path=/api/v1/auth" in header


def test_apply_device_cookie_renews_presented_secret_on_reuse() -> None:
    response = Response()
    apply_device_cookie(response, None, "presented-secret", Settings())
    header = response.headers["set-cookie"]
    assert "novel_device=presented-secret" in header
    assert f"Max-Age={365 * 86_400}" in header


def test_apply_device_cookie_omits_cookie_without_any_secret() -> None:
    response = Response()
    apply_device_cookie(response, None, None, Settings())
    assert "set-cookie" not in response.headers


def test_apply_device_cookie_uses_configured_independent_lifetime() -> None:
    response = Response()
    apply_device_cookie(response, "issued-secret", None, Settings(auth_device_cookie_ttl_days=30))
    header = response.headers["set-cookie"]
    assert f"Max-Age={30 * 86_400}" in header
