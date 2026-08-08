from fastapi import APIRouter

from novel_platform.api.dependencies.auth import CurrentAuth
from novel_platform.api.dependencies.database import DatabaseSession
from novel_platform.api.schemas import ProfilePatch, UserResponse
from novel_platform.api.serializers import user_response
from novel_platform.application.users.service import UserService

router = APIRouter(prefix="/users", tags=["profile"])


@router.patch("/me", response_model=UserResponse)
async def update_me(
    payload: ProfilePatch, session: DatabaseSession, current: CurrentAuth
) -> UserResponse:
    return user_response(
        await UserService(session).update_me(current, payload.display_name),
        current.capabilities,
    )
