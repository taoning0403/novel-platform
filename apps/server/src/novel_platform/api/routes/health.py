from http import HTTPStatus

from fastapi import APIRouter
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from novel_platform.api.dependencies.database import DatabaseSession
from novel_platform.api.schemas import HealthResponse
from novel_platform.application.errors import ApplicationError

router = APIRouter(prefix="/health", tags=["health"])


@router.get("/live", response_model=HealthResponse)
async def live() -> HealthResponse:
    return HealthResponse(status="ok")


@router.get("/ready", response_model=HealthResponse)
async def ready(session: DatabaseSession) -> HealthResponse:
    try:
        await session.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        raise ApplicationError(
            "database_unavailable",
            "The database is not ready.",
            status_code=HTTPStatus.SERVICE_UNAVAILABLE,
        ) from exc
    return HealthResponse(status="ok")
