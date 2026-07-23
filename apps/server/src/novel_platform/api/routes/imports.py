from typing import Annotated
from uuid import UUID

from anyio import to_thread
from fastapi import APIRouter, File, Form, Response, UploadFile, status

from novel_platform.api.dependencies.auth import CurrentAuth
from novel_platform.api.dependencies.database import DatabaseSession
from novel_platform.api.dependencies.storage import FileStorageDependency
from novel_platform.api.file_responses import temporary_file_response
from novel_platform.api.library_responses import LibraryResponseBuilder
from novel_platform.api.schemas import ImportCommitRequest, ImportCommitResponse, ImportResponse
from novel_platform.api.serializers import import_response
from novel_platform.application.access import LibraryAccessService
from novel_platform.application.errors import ApplicationError
from novel_platform.application.library.commands import CommitImport, InspectImport
from novel_platform.application.library.commit_service import ImportCommitService
from novel_platform.application.library.inspection_service import ImportInspectionService
from novel_platform.config import get_settings
from novel_platform.domain.errors import DomainRuleViolation
from novel_platform.domain.library.models import ImportOperation
from novel_platform.infrastructure.repositories.library import LibraryRepository

router = APIRouter(prefix="/imports", tags=["library-imports"])


@router.post("/inspect", response_model=ImportResponse, status_code=status.HTTP_201_CREATED)
async def inspect_import(
    file: Annotated[UploadFile, File()],
    operation: Annotated[ImportOperation, Form()],
    session: DatabaseSession,
    current: CurrentAuth,
    storage: FileStorageDependency,
    text_encoding: Annotated[str, Form()] = "auto",
    target_book_id: Annotated[UUID | None, Form()] = None,
    target_edition_id: Annotated[UUID | None, Form()] = None,
) -> ImportResponse:
    scope = await LibraryAccessService(session).require_upload(current)
    try:
        library_import = await ImportInspectionService(
            session,
            storage,
            get_settings(),
        ).inspect(
            scope=scope,
            command=InspectImport(
                operation=operation,
                filename=file.filename,
                submitted_media_type=file.content_type,
                requested_text_encoding=text_encoding,
                target_book_id=target_book_id,
                target_edition_id=target_edition_id,
            ),
            stream=file.file,
        )
    finally:
        await file.close()
    return import_response(library_import)


@router.post("/{import_id}/commit", response_model=ImportCommitResponse)
async def commit_import(
    import_id: UUID,
    payload: ImportCommitRequest,
    session: DatabaseSession,
    current: CurrentAuth,
    storage: FileStorageDependency,
) -> ImportCommitResponse:
    scope = await LibraryAccessService(session).require_upload(current)
    service = ImportCommitService(session, storage)
    try:
        result = await service.commit(
            scope=scope,
            import_id=import_id,
            command=CommitImport(**payload.model_dump()),
        )
    except (ApplicationError, DomainRuleViolation) as error:
        await service.record_expected_failure(
            scope=scope,
            import_id=import_id,
            error=error,
        )
        raise
    except Exception:
        await service.record_unexpected_failure(
            scope=scope,
            import_id=import_id,
        )
        raise
    file_record = await LibraryRepository(session).get_current_edition_file_for_owner(
        scope.owner_user_id,
        result.edition.id,
    )
    responses = LibraryResponseBuilder(session, scope)
    return ImportCommitResponse(
        upload=import_response(result.library_import),
        book=await responses.book(result.book),
        edition=await responses.edition(result.edition, file_record),
    )


@router.get("/{import_id}", response_model=ImportResponse)
async def get_import(
    import_id: UUID,
    session: DatabaseSession,
    current: CurrentAuth,
    storage: FileStorageDependency,
) -> ImportResponse:
    scope = await LibraryAccessService(session).require_upload(current)
    library_import = await ImportInspectionService(
        session,
        storage,
        get_settings(),
    ).get(scope, import_id)
    return import_response(library_import)


@router.delete("/{import_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_import(
    import_id: UUID,
    session: DatabaseSession,
    current: CurrentAuth,
    storage: FileStorageDependency,
) -> Response:
    scope = await LibraryAccessService(session).require_upload(current)
    await ImportInspectionService(session, storage, get_settings()).delete(
        scope,
        import_id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{import_id}/cover")
async def get_import_cover(
    import_id: UUID,
    session: DatabaseSession,
    current: CurrentAuth,
    storage: FileStorageDependency,
) -> Response:
    scope = await LibraryAccessService(session).require_upload(current)
    library_import = await ImportInspectionService(
        session,
        storage,
        get_settings(),
    ).get(scope, import_id)
    key = library_import.cover_temporary_storage_key
    if key is None or not await to_thread.run_sync(storage.temporary_exists, key):
        raise ApplicationError("file_not_found", "上传记录没有可预览封面。", status_code=404)
    return temporary_file_response(
        storage,
        key,
        media_type=library_import.cover_media_type or "application/octet-stream",
    )
