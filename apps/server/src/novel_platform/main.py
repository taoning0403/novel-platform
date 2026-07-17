import logging
import tempfile

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware

from novel_platform.api.dependencies.storage import get_file_storage
from novel_platform.api.errors import register_error_handlers
from novel_platform.api.middleware import UploadBodyLimitMiddleware
from novel_platform.api.routes import api_router
from novel_platform.api.schemas import ErrorResponse
from novel_platform.config import get_settings

settings = get_settings()
file_storage = get_file_storage()
file_storage.initialize()
tempfile.tempdir = str(file_storage.temporary_directory)
logging.basicConfig(level=settings.log_level.upper())

app = FastAPI(
    title=settings.app_name,
    version="0.8.0",
    docs_url="/api/docs" if settings.openapi_enabled else None,
    redoc_url=None,
    openapi_url="/openapi.json" if settings.openapi_enabled else None,
    responses={
        status_code: {"model": ErrorResponse}
        for status_code in (400, 401, 403, 404, 409, 413, 422, 429, 500)
    },
)
app.add_middleware(UploadBodyLimitMiddleware, max_file_bytes=settings.max_upload_bytes)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.trusted_hosts)
register_error_handlers(app)
app.include_router(api_router)


@app.middleware("http")
async def noindex_private_content(request: Request, call_next):  # type: ignore[no-untyped-def]
    response = await call_next(request)
    if request.url.path not in {"/api/v1/health/live", "/api/v1/health/ready"}:
        response.headers["X-Robots-Tag"] = "noindex, nofollow, noarchive"
    return response
