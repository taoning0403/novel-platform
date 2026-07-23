from uuid import UUID

from fastapi import APIRouter, Response, status

from novel_platform.api.dependencies.auth import CurrentAuth
from novel_platform.api.dependencies.database import DatabaseSession
from novel_platform.api.dependencies.storage import FileStorageDependency
from novel_platform.api.schemas import EditionCreate, EditionPatch, EditionResponse
from novel_platform.api.serializers import edition_response
from novel_platform.application.access import LibraryAccessService
from novel_platform.application.books.service import BookService
from novel_platform.application.editions.commands import CreateEdition, UpdateEdition
from novel_platform.application.editions.service import EditionService
from novel_platform.application.library.file_service import LibraryFileService
from novel_platform.infrastructure.repositories.library import LibraryRepository
from novel_platform.infrastructure.repositories.reader import ReaderRepository

router = APIRouter(prefix="/books/{book_id}/editions", tags=["editions"])


@router.post("", response_model=EditionResponse, status_code=status.HTTP_201_CREATED)
async def create_edition(
    book_id: UUID,
    payload: EditionCreate,
    session: DatabaseSession,
    current: CurrentAuth,
) -> EditionResponse:
    owner_user_id = await LibraryAccessService(session).require_manager(current)
    edition = await EditionService(session).create(
        book_id,
        owner_user_id,
        CreateEdition(
            title=payload.title,
            language=payload.language,
            content_role=payload.content_role,
            translation_origin=payload.translation_origin,
            creation_method=payload.creation_method,
            source_edition_id=payload.source_edition_id,
            supersedes_edition_id=payload.supersedes_edition_id,
            status=payload.status,
            revision=payload.revision,
            metadata=payload.metadata,
        ),
        created_by_user_id=current.user.id,
    )
    return edition_response(edition)


@router.get("", response_model=list[EditionResponse])
async def list_editions(
    book_id: UUID,
    session: DatabaseSession,
    current: CurrentAuth,
) -> list[EditionResponse]:
    scope = await LibraryAccessService(session).scope(current)
    books = BookService(session)
    if scope.can_manage:
        _, editions = await books.detail(book_id, scope.owner_user_id)
    else:
        _, editions = await books.readable_detail(book_id, scope.owner_user_id)
    library = LibraryRepository(session)
    progresses = await ReaderRepository(session).progress_for_editions(
        scope.viewer_user_id,
        [edition.id for edition in editions],
    )
    return [
        edition_response(
            edition,
            await library.get_current_edition_file_for_owner(scope.owner_user_id, edition.id),
            progresses.get(edition.id),
            include_download=scope.can_manage,
        )
        for edition in editions
    ]


@router.get("/{edition_id}", response_model=EditionResponse)
async def get_edition(
    book_id: UUID,
    edition_id: UUID,
    session: DatabaseSession,
    current: CurrentAuth,
) -> EditionResponse:
    scope = await LibraryAccessService(session).scope(current)
    service = EditionService(session)
    if scope.can_manage:
        edition = await service.get(book_id, scope.owner_user_id, edition_id)
    else:
        edition = await service.get_readable(book_id, scope.owner_user_id, edition_id)
    file_record = await LibraryRepository(session).get_current_edition_file_for_owner(
        scope.owner_user_id,
        edition.id,
    )
    progress = await ReaderRepository(session).get_progress(scope.viewer_user_id, edition.id)
    return edition_response(
        edition,
        file_record,
        progress,
        include_download=scope.can_manage,
    )


@router.patch("/{edition_id}", response_model=EditionResponse)
async def update_edition(
    book_id: UUID,
    edition_id: UUID,
    payload: EditionPatch,
    session: DatabaseSession,
    current: CurrentAuth,
) -> EditionResponse:
    owner_user_id = await LibraryAccessService(session).require_manager(current)
    edition = await EditionService(session).update(
        book_id,
        owner_user_id,
        edition_id,
        UpdateEdition(changes=payload.model_dump(exclude_unset=True)),
    )
    file_record = await LibraryRepository(session).get_current_edition_file_for_owner(
        owner_user_id,
        edition.id,
    )
    progress = await ReaderRepository(session).get_progress(current.user.id, edition.id)
    return edition_response(edition, file_record, progress)


@router.delete("/{edition_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_edition(
    book_id: UUID,
    edition_id: UUID,
    session: DatabaseSession,
    current: CurrentAuth,
    storage: FileStorageDependency,
) -> Response:
    owner_user_id = await LibraryAccessService(session).require_manager(current)
    await LibraryFileService(session, storage).delete_edition(
        owner_user_id=owner_user_id,
        book_id=book_id,
        edition_id=edition_id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
