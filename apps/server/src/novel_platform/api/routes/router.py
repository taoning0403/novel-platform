from fastapi import APIRouter

from novel_platform.api.routes import (
    audit,
    auth,
    books,
    devices,
    editions,
    files,
    health,
    imports,
    preferences,
    reader,
    readers,
    series,
    site,
    translation_runs,
    users,
)

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(users.router)
api_router.include_router(devices.router)
api_router.include_router(books.router)
api_router.include_router(editions.router)
api_router.include_router(files.router)
api_router.include_router(imports.router)
api_router.include_router(preferences.router)
api_router.include_router(reader.router)
api_router.include_router(series.router)
api_router.include_router(readers.router)
api_router.include_router(site.router)
api_router.include_router(audit.router)
api_router.include_router(translation_runs.router)
