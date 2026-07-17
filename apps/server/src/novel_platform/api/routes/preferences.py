from uuid import UUID

from fastapi import APIRouter

from novel_platform.api.dependencies.auth import CurrentAuth
from novel_platform.api.dependencies.database import DatabaseSession
from novel_platform.api.schemas import BookPreferencePatch, BookPreferenceResponse
from novel_platform.application.access import LibraryAccessService
from novel_platform.application.preferences.service import PreferenceService

router = APIRouter(prefix="/books/{book_id}/preferences", tags=["book-preferences"])


@router.get("", response_model=BookPreferenceResponse)
async def get_preferences(
    book_id: UUID, session: DatabaseSession, current: CurrentAuth
) -> BookPreferenceResponse:
    scope = await LibraryAccessService(session).scope(current)
    preference = await PreferenceService(session).get(
        scope.viewer_user_id,
        scope.owner_user_id,
        book_id,
        readable_only=not scope.can_manage,
    )
    if preference is None:
        return BookPreferenceResponse(
            preferred_edition_id=None,
            last_opened_edition_id=None,
        )
    return BookPreferenceResponse.model_validate(preference, from_attributes=True)


@router.patch("", response_model=BookPreferenceResponse)
async def update_preferences(
    book_id: UUID,
    payload: BookPreferencePatch,
    session: DatabaseSession,
    current: CurrentAuth,
) -> BookPreferenceResponse:
    scope = await LibraryAccessService(session).scope(current)
    preference = await PreferenceService(session).update(
        scope.viewer_user_id,
        scope.owner_user_id,
        book_id,
        payload.model_dump(exclude_unset=True),
        readable_only=not scope.can_manage,
    )
    return BookPreferenceResponse.model_validate(preference, from_attributes=True)
