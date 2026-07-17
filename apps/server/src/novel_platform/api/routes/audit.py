from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query

from novel_platform.api.dependencies.auth import CurrentAdmin
from novel_platform.api.dependencies.database import DatabaseSession
from novel_platform.api.schemas import SecurityAuditEventResponse
from novel_platform.api.serializers import audit_event_response
from novel_platform.application.auth.audit_service import AuditService

router = APIRouter(prefix="/admin/audit", tags=["security-audit"])


@router.get("", response_model=list[SecurityAuditEventResponse])
async def list_audit_events(
    session: DatabaseSession,
    _admin: CurrentAdmin,
    event_type: str | None = None,
    subject_user_id: UUID | None = None,
    outcome: str | None = None,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[SecurityAuditEventResponse]:
    rows = await AuditService(session).list_events(
        event_type=event_type,
        subject_user_id=subject_user_id,
        outcome=outcome,
        created_from=created_from,
        created_to=created_to,
        limit=limit,
        offset=offset,
    )
    return [audit_event_response(row) for row in rows]
