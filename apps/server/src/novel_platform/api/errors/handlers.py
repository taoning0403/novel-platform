import logging
from collections.abc import Mapping
from http import HTTPStatus
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError

from novel_platform.application.errors import ApplicationError
from novel_platform.config import get_settings
from novel_platform.domain.errors import DomainRuleViolation

logger = logging.getLogger(__name__)


def error_response(
    *,
    status_code: int,
    code: str,
    message: str,
    details: dict[str, Any] | None = None,
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message, "details": details or {}}},
        headers=headers,
    )


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApplicationError)
    async def handle_application_error(request: Request, exc: ApplicationError) -> JSONResponse:
        response = error_response(
            status_code=exc.status_code,
            code=exc.code,
            message=exc.message,
            details=exc.details,
            headers=exc.headers,
        )
        if request.url.path == "/api/v1/auth/refresh" and exc.status_code == 401:
            settings = get_settings()
            response.delete_cookie(
                key=settings.auth_cookie_name,
                httponly=True,
                secure=settings.auth_cookie_secure,
                samesite=settings.auth_cookie_samesite,
                domain=settings.auth_cookie_domain,
                path="/api/v1/auth",
            )
        return response

    @app.exception_handler(DomainRuleViolation)
    async def handle_domain_error(_request: Request, exc: DomainRuleViolation) -> JSONResponse:
        return error_response(
            status_code=HTTPStatus.BAD_REQUEST,
            code=exc.code,
            message=exc.message,
            details=exc.details,
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        _request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        safe_errors = [
            {
                "location": [str(part) for part in item["loc"]],
                "message": item["msg"],
                "type": item["type"],
            }
            for item in exc.errors()
        ]
        return error_response(
            status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
            code="validation_error",
            message="The request payload is invalid.",
            details={"errors": safe_errors},
        )

    @app.exception_handler(IntegrityError)
    async def handle_integrity_error(_request: Request, exc: IntegrityError) -> JSONResponse:
        logger.warning("Database integrity error", exc_info=exc)
        return error_response(
            status_code=HTTPStatus.CONFLICT,
            code="database_constraint_violation",
            message="The requested change conflicts with a data constraint.",
        )

    @app.exception_handler(HTTPException)
    async def handle_http_error(_request: Request, exc: HTTPException) -> JSONResponse:
        try:
            phrase = HTTPStatus(exc.status_code).phrase
        except ValueError:
            phrase = "Request failed"
        return error_response(
            status_code=exc.status_code,
            code="http_error",
            message=phrase,
            headers=exc.headers,
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_error(_request: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled API error", exc_info=exc)
        return error_response(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            code="internal_error",
            message="An unexpected server error occurred.",
        )
