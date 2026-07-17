from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, Response

from novel_platform.api.dependencies.auth import CurrentAuth
from novel_platform.api.dependencies.database import DatabaseSession
from novel_platform.api.dependencies.storage import FileStorageDependency
from novel_platform.api.schemas import (
    ReaderEditionOption,
    ReaderOpenResponse,
    ReaderPublicationResponse,
    ReaderSectionDescriptor,
    ReaderSectionResponse,
    ReaderSettingsPatch,
    ReaderSettingsResponse,
    ReaderTocEntry,
    ReadingProgressResponse,
    ReadingProgressUpdate,
    RecentReadingResponse,
)
from novel_platform.api.serializers import book_response
from novel_platform.application.access import LibraryAccessService
from novel_platform.application.reader.service import (
    OpenedReader,
    ReaderEditionRecord,
    ReaderService,
)
from novel_platform.config import get_settings
from novel_platform.domain.reader.models import ReadingStatus
from novel_platform.infrastructure.database.models import ReaderSettingsModel, ReadingProgressModel

router = APIRouter(tags=["reader"])


def progress_response(progress: ReadingProgressModel) -> ReadingProgressResponse:
    return ReadingProgressResponse(
        edition_id=progress.edition_id,
        status=progress.status,
        section_id=progress.section_id,
        block_id=progress.block_id,
        section_progress=progress.section_progress,
        overall_progress=progress.overall_progress,
        edition_file_revision=progress.edition_file_revision,
        version=progress.version,
        last_read_at=progress.last_read_at,
    )


def settings_response(settings: ReaderSettingsModel) -> ReaderSettingsResponse:
    return ReaderSettingsResponse(
        font_size=settings.font_size,
        line_height=settings.line_height,
        content_width=settings.content_width,
        font_family=settings.font_family,
        theme=settings.theme,
        updated_at=settings.updated_at,
    )


def edition_option(record: ReaderEditionRecord) -> ReaderEditionOption:
    progress = record.progress
    return ReaderEditionOption(
        id=record.edition.id,
        book_id=record.edition.book_id,
        title=record.edition.title,
        language=record.edition.language,
        content_role=record.edition.content_role,
        translation_origin=record.edition.translation_origin,
        file_format=record.file.stored_file.file_format,
        reading_status=progress.status if progress else ReadingStatus.NOT_STARTED,
        reading_progress=progress.overall_progress if progress else 0,
        last_read_at=progress.last_read_at if progress else None,
    )


def open_response(opened: OpenedReader) -> ReaderOpenResponse:
    options = [edition_option(record) for record in opened.editions]
    current = next(option for option in options if option.id == opened.edition.id)
    return ReaderOpenResponse(
        book=book_response(opened.book),
        edition=current,
        available_editions=options,
        publication=ReaderPublicationResponse(
            file_format=opened.publication.file_format,
            file_revision=opened.publication.file_revision,
            sections=[
                ReaderSectionDescriptor(id=section.id, index=section.index, title=section.title)
                for section in opened.publication.sections
            ],
            toc=[
                ReaderTocEntry(title=item.title, section_id=item.section_id)
                for item in opened.publication.toc
            ],
        ),
        progress=progress_response(opened.progress),
        settings=settings_response(opened.settings),
    )


@router.post("/editions/{edition_id}/reader/open", response_model=ReaderOpenResponse)
async def open_reader(
    edition_id: UUID,
    session: DatabaseSession,
    current: CurrentAuth,
    storage: FileStorageDependency,
) -> ReaderOpenResponse:
    scope = await LibraryAccessService(session).scope(current)
    opened = await ReaderService(session, storage, get_settings()).open(
        owner_user_id=scope.owner_user_id,
        viewer_user_id=scope.viewer_user_id,
        device_id=current.device.id,
        edition_id=edition_id,
        readable_only=not scope.can_manage,
    )
    return open_response(opened)


@router.get(
    "/editions/{edition_id}/reader/sections/{section_id}",
    response_model=ReaderSectionResponse,
)
async def get_reader_section(
    edition_id: UUID,
    section_id: str,
    session: DatabaseSession,
    current: CurrentAuth,
    storage: FileStorageDependency,
) -> ReaderSectionResponse:
    scope = await LibraryAccessService(session).scope(current)
    content = await ReaderService(session, storage, get_settings()).section(
        owner_user_id=scope.owner_user_id,
        edition_id=edition_id,
        section_id=section_id,
        readable_only=not scope.can_manage,
    )
    return ReaderSectionResponse(
        id=content.section.id,
        index=content.section.index,
        title=content.section.title,
        html=content.html,
        resource_ids=list(content.resource_ids),
    )


@router.get("/editions/{edition_id}/reader/resources/{resource_id}")
async def get_reader_resource(
    edition_id: UUID,
    resource_id: str,
    session: DatabaseSession,
    current: CurrentAuth,
    storage: FileStorageDependency,
) -> Response:
    scope = await LibraryAccessService(session).scope(current)
    resource = await ReaderService(session, storage, get_settings()).resource(
        owner_user_id=scope.owner_user_id,
        edition_id=edition_id,
        resource_id=resource_id,
        readable_only=not scope.can_manage,
    )
    return Response(
        content=resource.content,
        media_type=resource.media_type,
        headers={
            "Cache-Control": "private, max-age=300",
            "Content-Security-Policy": "default-src 'none'; sandbox",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.patch(
    "/editions/{edition_id}/reader/progress",
    response_model=ReadingProgressResponse,
)
async def save_reader_progress(
    edition_id: UUID,
    payload: ReadingProgressUpdate,
    session: DatabaseSession,
    current: CurrentAuth,
    storage: FileStorageDependency,
) -> ReadingProgressResponse:
    scope = await LibraryAccessService(session).scope(current)
    progress = await ReaderService(session, storage, get_settings()).save_progress(
        owner_user_id=scope.owner_user_id,
        viewer_user_id=scope.viewer_user_id,
        device_id=current.device.id,
        edition_id=edition_id,
        expected_version=payload.expected_version,
        section_id=payload.section_id,
        block_id=payload.block_id,
        section_progress=payload.section_progress,
        overall_progress=payload.overall_progress,
        edition_file_revision=payload.edition_file_revision,
        status=payload.status,
        readable_only=not scope.can_manage,
    )
    return progress_response(progress)


@router.get("/reader/settings", response_model=ReaderSettingsResponse)
async def get_reader_settings(
    session: DatabaseSession,
    current: CurrentAuth,
    storage: FileStorageDependency,
) -> ReaderSettingsResponse:
    settings = await ReaderService(session, storage, get_settings()).get_settings(current.user.id)
    return settings_response(settings)


@router.patch("/reader/settings", response_model=ReaderSettingsResponse)
async def update_reader_settings(
    payload: ReaderSettingsPatch,
    session: DatabaseSession,
    current: CurrentAuth,
    storage: FileStorageDependency,
) -> ReaderSettingsResponse:
    settings = await ReaderService(session, storage, get_settings()).update_settings(
        current.user.id,
        payload.model_dump(exclude_unset=True),
    )
    return settings_response(settings)


@router.get("/reader/recent", response_model=list[RecentReadingResponse])
async def recent_reading(
    session: DatabaseSession,
    current: CurrentAuth,
    storage: FileStorageDependency,
    limit: Annotated[int, Query(ge=1, le=50)] = 12,
) -> list[RecentReadingResponse]:
    scope = await LibraryAccessService(session).scope(current)
    records = await ReaderService(session, storage, get_settings()).recent(
        scope.viewer_user_id,
        scope.owner_user_id,
        limit=limit,
        readable_only=not scope.can_manage,
    )
    return [
        RecentReadingResponse(
            book_id=record.book.id,
            book_title=record.book.canonical_title,
            book_cover_thumbnail_url=(
                f"/api/v1/books/{record.book.id}/cover?thumbnail=true"
                if record.book.cover_thumbnail_file_id
                else None
            ),
            edition_id=record.edition.id,
            edition_title=record.edition.title,
            edition_language=record.edition.language,
            file_format=record.file_format,
            series_id=record.series_id,
            series_name=record.series_name,
            status=record.progress.status,
            progress=record.progress.overall_progress,
            last_read_at=record.progress.last_read_at,
            continue_url=f"/read/{record.edition.id}",
        )
        for record in records
    ]
