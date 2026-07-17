from uuid import UUID

from fastapi import APIRouter, Response

from novel_platform.api.dependencies.auth import CurrentAuth
from novel_platform.api.dependencies.database import DatabaseSession
from novel_platform.api.dependencies.storage import FileStorageDependency
from novel_platform.api.file_responses import stored_file_response
from novel_platform.application.access import LibraryAccessService
from novel_platform.application.library.file_service import LibraryFileService

router = APIRouter(prefix="/editions", tags=["edition-files"])


@router.get("/{edition_id}/file")
async def download_edition_file(
    edition_id: UUID,
    session: DatabaseSession,
    current: CurrentAuth,
    storage: FileStorageDependency,
) -> Response:
    owner_user_id = await LibraryAccessService(session).require_manager(current)
    downloadable = await LibraryFileService(session, storage).edition_download(
        owner_user_id,
        edition_id,
    )
    return stored_file_response(storage, downloadable.stored_file, attachment=True)
