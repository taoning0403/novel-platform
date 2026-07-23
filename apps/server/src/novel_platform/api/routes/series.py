from uuid import UUID

from fastapi import APIRouter, Response, status

from novel_platform.api.dependencies.auth import CurrentAuth
from novel_platform.api.dependencies.database import DatabaseSession
from novel_platform.api.library_responses import LibraryResponseBuilder
from novel_platform.api.schemas import (
    SeriesCreate,
    SeriesDetailResponse,
    SeriesPatch,
    SeriesResponse,
)
from novel_platform.api.serializers import series_response
from novel_platform.application.access import LibraryAccessService
from novel_platform.application.series.service import SeriesService
from novel_platform.infrastructure.repositories.library import LibraryRepository

router = APIRouter(prefix="/series", tags=["series"])


@router.post("", response_model=SeriesResponse, status_code=status.HTTP_201_CREATED)
async def create_series(
    payload: SeriesCreate,
    session: DatabaseSession,
    current: CurrentAuth,
) -> SeriesResponse:
    owner_user_id = await LibraryAccessService(session).require_manager(current)
    series = await SeriesService(session).create(
        owner_user_id,
        name=payload.name,
        description=payload.description,
    )
    return series_response(series, 0)


@router.get("", response_model=list[SeriesResponse])
async def list_series(
    session: DatabaseSession,
    current: CurrentAuth,
) -> list[SeriesResponse]:
    scope = await LibraryAccessService(session).scope(current)
    service = SeriesService(session)
    rows = (
        await service.list_all(scope.owner_user_id)
        if scope.can_manage
        else await service.list_readable(scope.owner_user_id)
    )
    return [series_response(series, book_count) for series, book_count in rows]


@router.get("/{series_id}", response_model=SeriesDetailResponse)
async def get_series(
    series_id: UUID,
    session: DatabaseSession,
    current: CurrentAuth,
) -> SeriesDetailResponse:
    scope = await LibraryAccessService(session).scope(current)
    service = SeriesService(session)
    if scope.can_manage:
        series, records = await service.detail(scope.owner_user_id, series_id)
    else:
        series, records = await service.readable_detail(scope.owner_user_id, series_id)
    library = LibraryRepository(session)
    summaries = await library.book_summaries(
        owner_user_id=scope.owner_user_id,
        viewer_user_id=scope.viewer_user_id,
        book_ids=[record.book.id for record in records],
        readable_only=not scope.can_manage,
    )
    responses = LibraryResponseBuilder(session, scope)
    return SeriesDetailResponse(
        **series_response(series, len(records)).model_dump(),
        books=[
            await responses.book_list_item(
                record.book,
                record.edition_count,
                summaries.get(record.book.id),
                series_id=series.id,
                series_name=series.name,
                series_position=record.membership.position,
            )
            for record in records
        ],
    )


@router.patch("/{series_id}", response_model=SeriesResponse)
async def update_series(
    series_id: UUID,
    payload: SeriesPatch,
    session: DatabaseSession,
    current: CurrentAuth,
) -> SeriesResponse:
    owner_user_id = await LibraryAccessService(session).require_manager(current)
    series = await SeriesService(session).update(
        owner_user_id,
        series_id,
        payload.model_dump(exclude_unset=True),
    )
    _, records = await SeriesService(session).detail(owner_user_id, series.id)
    return series_response(series, len(records))


@router.delete("/{series_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_series(
    series_id: UUID,
    session: DatabaseSession,
    current: CurrentAuth,
) -> Response:
    owner_user_id = await LibraryAccessService(session).require_manager(current)
    await SeriesService(session).delete(owner_user_id, series_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{series_id}/books/{book_id}",
    response_model=SeriesDetailResponse,
)
async def add_book_to_series(
    series_id: UUID,
    book_id: UUID,
    session: DatabaseSession,
    current: CurrentAuth,
) -> SeriesDetailResponse:
    owner_user_id = await LibraryAccessService(session).require_manager(current)
    await SeriesService(session).add_book(owner_user_id, series_id, book_id)
    return await get_series(series_id, session, current)


@router.delete("/{series_id}/books/{book_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_book_from_series(
    series_id: UUID,
    book_id: UUID,
    session: DatabaseSession,
    current: CurrentAuth,
) -> Response:
    owner_user_id = await LibraryAccessService(session).require_manager(current)
    await SeriesService(session).remove_book(owner_user_id, series_id, book_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
