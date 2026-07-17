from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Query, Response, status

from novel_platform.api.dependencies.auth import CurrentAuth
from novel_platform.api.dependencies.database import DatabaseSession
from novel_platform.api.dependencies.storage import FileStorageDependency
from novel_platform.api.file_responses import stored_file_response
from novel_platform.api.schemas import (
    BookCreate,
    BookDetailResponse,
    BookListItem,
    BookPatch,
    BookResponse,
)
from novel_platform.api.serializers import book_detail_response, book_list_item, book_response
from novel_platform.application.access import LibraryAccessService
from novel_platform.application.books.commands import CreateBook, UpdateBook
from novel_platform.application.books.service import BookService
from novel_platform.application.library.file_service import LibraryFileService
from novel_platform.domain.editions.models import ContentRole
from novel_platform.domain.library.models import FileFormat
from novel_platform.infrastructure.repositories.library import LibraryRepository
from novel_platform.infrastructure.repositories.reader import ReaderRepository
from novel_platform.infrastructure.repositories.series import SeriesRepository

router = APIRouter(prefix="/books", tags=["books"])


@router.post("", response_model=BookResponse, status_code=status.HTTP_201_CREATED)
async def create_book(
    payload: BookCreate, session: DatabaseSession, current: CurrentAuth
) -> BookResponse:
    owner_user_id = await LibraryAccessService(session).require_manager(current)
    book = await BookService(session).create(
        CreateBook(
            canonical_title=payload.canonical_title,
            canonical_author=payload.canonical_author,
            description=payload.description,
            metadata=payload.metadata,
        ),
        owner_user_id,
    )
    return book_response(book)


@router.get("", response_model=list[BookListItem])
async def list_books(
    session: DatabaseSession,
    current: CurrentAuth,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
    page: Annotated[int | None, Query(ge=1)] = None,
    page_size: Annotated[int | None, Query(ge=1, le=100)] = None,
    query: Annotated[str | None, Query(max_length=200)] = None,
    file_format: Annotated[FileFormat | None, Query(alias="format")] = None,
    language: Annotated[str | None, Query(max_length=40)] = None,
    edition_type: ContentRole | None = None,
    sort: Literal["updated_desc", "created_desc", "title_asc"] = "updated_desc",
) -> list[BookListItem]:
    scope = await LibraryAccessService(session).scope(current)
    effective_limit = page_size or limit
    effective_offset = ((page or 1) - 1) * effective_limit if page is not None else offset
    book_service = BookService(session)
    list_method = book_service.list_page if scope.can_manage else book_service.list_readable_page
    rows = await list_method(
        owner_user_id=scope.owner_user_id,
        limit=effective_limit,
        offset=effective_offset,
        query=query,
        file_format=file_format,
        language=language,
        edition_type=edition_type,
        sort=sort,
    )
    summaries = await LibraryRepository(session).book_summaries(
        owner_user_id=scope.owner_user_id,
        viewer_user_id=scope.viewer_user_id,
        book_ids=[book.id for book, _ in rows],
        readable_only=not scope.can_manage,
    )
    memberships = await SeriesRepository(session).membership_summaries(
        scope.owner_user_id,
        [book.id for book, _ in rows],
    )
    return [
        book_list_item(
            book,
            count,
            summaries.get(book.id),
            series_id=memberships.get(book.id, (None, None))[0],
            series_name=memberships.get(book.id, (None, None))[1],
        )
        for book, count in rows
    ]


@router.get("/{book_id}", response_model=BookDetailResponse)
async def get_book(
    book_id: UUID, session: DatabaseSession, current: CurrentAuth
) -> BookDetailResponse:
    scope = await LibraryAccessService(session).scope(current)
    book_service = BookService(session)
    if scope.can_manage:
        book, editions = await book_service.detail(book_id, scope.owner_user_id)
    else:
        book, editions = await book_service.readable_detail(book_id, scope.owner_user_id)
    library = LibraryRepository(session)
    files = {
        edition.id: record
        for edition in editions
        if (
            record := await library.get_current_edition_file_for_owner(
                scope.owner_user_id,
                edition.id,
            )
        )
        is not None
    }
    progresses = await ReaderRepository(session).progress_for_editions(
        scope.viewer_user_id,
        [edition.id for edition in editions],
    )
    return book_detail_response(
        book,
        editions,
        files,
        progresses,
        include_download=scope.can_manage,
    )


@router.patch("/{book_id}", response_model=BookResponse)
async def update_book(
    book_id: UUID,
    payload: BookPatch,
    session: DatabaseSession,
    current: CurrentAuth,
) -> BookResponse:
    owner_user_id = await LibraryAccessService(session).require_manager(current)
    book = await BookService(session).update(
        book_id,
        owner_user_id,
        UpdateBook(changes=payload.model_dump(exclude_unset=True)),
    )
    return book_response(book)


@router.delete("/{book_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_book(
    book_id: UUID,
    session: DatabaseSession,
    current: CurrentAuth,
    storage: FileStorageDependency,
) -> Response:
    owner_user_id = await LibraryAccessService(session).require_manager(current)
    await LibraryFileService(session, storage).delete_book(
        owner_user_id=owner_user_id,
        book_id=book_id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{book_id}/cover")
async def get_book_cover(
    book_id: UUID,
    session: DatabaseSession,
    current: CurrentAuth,
    storage: FileStorageDependency,
    thumbnail: bool = False,
) -> Response:
    scope = await LibraryAccessService(session).scope(current)
    if not scope.can_manage:
        await BookService(session).readable_detail(book_id, scope.owner_user_id)
    downloadable = await LibraryFileService(session, storage).book_cover(
        scope.owner_user_id,
        book_id,
        thumbnail=thumbnail,
    )
    return stored_file_response(storage, downloadable.stored_file, attachment=False)
