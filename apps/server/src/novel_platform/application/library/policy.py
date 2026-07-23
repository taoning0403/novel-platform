from dataclasses import dataclass
from http import HTTPStatus
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from novel_platform.application.access import LibraryAccessScope
from novel_platform.application.errors import ApplicationError
from novel_platform.domain.auth.capabilities import CredentialCapability
from novel_platform.domain.editions.models import ContentRole, CreationMethod, EditionStatus
from novel_platform.domain.library.models import FileFormat, ImportStatus
from novel_platform.domain.translations.models import ACTIVE_TRANSLATION_RUN_STATUSES
from novel_platform.infrastructure.database.models import (
    BookEditionModel,
    BookModel,
    EditionFileModel,
    EditionTranslationRunModel,
    LibraryImportModel,
    StoredFileModel,
)
from novel_platform.infrastructure.repositories.editions import EditionRepository
from novel_platform.infrastructure.repositories.library import EditionFileRecord, LibraryRepository


@dataclass(frozen=True, slots=True)
class ResourcePermissions:
    can_edit: bool
    can_delete: bool
    can_upload_edition: bool
    can_translate: bool


class LibraryResourcePolicy:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.editions = EditionRepository(session)
        self.library = LibraryRepository(session)

    @staticmethod
    def require_upload_capability(scope: LibraryAccessScope) -> None:
        if not scope.has(CredentialCapability.LIBRARY_UPLOAD):
            raise ApplicationError(
                "library_capability_required",
                "当前访问凭证不包含上传能力。",
                status_code=HTTPStatus.FORBIDDEN,
                details={"capability": CredentialCapability.LIBRARY_UPLOAD.value},
            )

    @staticmethod
    def require_translation_capability(scope: LibraryAccessScope) -> None:
        if not scope.has(CredentialCapability.TRANSLATION_USE):
            raise ApplicationError(
                "library_capability_required",
                "当前访问凭证不包含翻译能力。",
                status_code=HTTPStatus.FORBIDDEN,
                details={"capability": CredentialCapability.TRANSLATION_USE.value},
            )

    @staticmethod
    def require_import_access(
        scope: LibraryAccessScope,
        library_import: LibraryImportModel,
    ) -> None:
        if not scope.can_manage and library_import.requested_by_user_id != scope.viewer_user_id:
            raise ApplicationError("upload_not_found", "上传记录不存在。", status_code=404)

    async def require_book_edit(
        self,
        scope: LibraryAccessScope,
        book: BookModel,
    ) -> None:
        self.require_upload_capability(scope)
        if not scope.can_manage and book.created_by_user_id != scope.viewer_user_id:
            self._forbidden()

    async def require_edition_edit(
        self,
        scope: LibraryAccessScope,
        edition: BookEditionModel,
    ) -> None:
        self.require_upload_capability(scope)
        if scope.can_manage:
            return
        if (
            edition.created_by_user_id != scope.viewer_user_id
            or edition.creation_method is not CreationMethod.UPLOADED
        ):
            self._forbidden()

    async def require_edition_replace(
        self,
        scope: LibraryAccessScope,
        edition: BookEditionModel,
    ) -> None:
        await self.require_edition_edit(scope, edition)

    async def require_book_delete(
        self,
        scope: LibraryAccessScope,
        book: BookModel,
    ) -> None:
        self.require_upload_capability(scope)
        if not scope.can_manage:
            if book.created_by_user_id != scope.viewer_user_id:
                self._forbidden()
            other_editions = await self.session.scalar(
                select(func.count(BookEditionModel.id)).where(
                    BookEditionModel.book_id == book.id,
                    BookEditionModel.created_by_user_id != scope.viewer_user_id,
                )
            )
            other_runs = await self.session.scalar(
                select(func.count(EditionTranslationRunModel.id)).where(
                    EditionTranslationRunModel.book_id == book.id,
                    EditionTranslationRunModel.created_by_user_id != scope.viewer_user_id,
                )
            )
            if other_editions or other_runs:
                raise ApplicationError(
                    "book_contains_other_contributions",
                    "作品包含其他贡献者的版本或翻译任务，不能整本删除。",
                    status_code=HTTPStatus.CONFLICT,
                )
        await self._require_no_active_import(book_id=book.id)
        if await self._has_active_run(book_id=book.id):
            raise ApplicationError(
                "translation_run_active",
                "作品仍有活动翻译任务，请先终止并完成清理。",
                status_code=HTTPStatus.CONFLICT,
            )

    async def require_edition_delete(
        self,
        scope: LibraryAccessScope,
        edition: BookEditionModel,
    ) -> None:
        allowed = scope.can_manage
        if edition.created_by_user_id == scope.viewer_user_id:
            if edition.creation_method is CreationMethod.UPLOADED:
                allowed = scope.has(CredentialCapability.LIBRARY_UPLOAD)
            elif edition.creation_method is CreationMethod.GENERATED:
                allowed = scope.has(CredentialCapability.TRANSLATION_USE)
        if not allowed:
            self._forbidden()

        dependents = await self.editions.dependents(edition.id)
        if dependents:
            raise ApplicationError(
                "edition_dependency_conflict",
                "其他 Edition 仍依赖该版本，请先解除 source 或 supersedes 关系。",
                status_code=HTTPStatus.CONFLICT,
            )
        run_count = await self.session.scalar(
            select(func.count(EditionTranslationRunModel.id)).where(
                or_(
                    EditionTranslationRunModel.source_edition_id == edition.id,
                    EditionTranslationRunModel.supersedes_edition_id == edition.id,
                )
            )
        )
        if run_count:
            raise ApplicationError(
                "edition_translation_history_conflict",
                "翻译任务历史仍引用该版本，不能删除。",
                status_code=HTTPStatus.CONFLICT,
            )
        await self._require_no_active_import(edition_id=edition.id)

    async def book_permissions(
        self,
        scope: LibraryAccessScope,
        book: BookModel,
    ) -> ResourcePermissions:
        has_upload = scope.has(CredentialCapability.LIBRARY_UPLOAD)
        has_translation = scope.has(CredentialCapability.TRANSLATION_USE)
        owns_book = book.created_by_user_id == scope.viewer_user_id
        can_edit = scope.can_manage or (has_upload and owns_book)
        can_delete = scope.can_manage or (has_upload and owns_book)
        if can_delete and not scope.can_manage:
            other_contributions = await self.session.scalar(
                select(func.count(BookEditionModel.id)).where(
                    BookEditionModel.book_id == book.id,
                    BookEditionModel.created_by_user_id != scope.viewer_user_id,
                )
            )
            if not other_contributions:
                other_contributions = await self.session.scalar(
                    select(func.count(EditionTranslationRunModel.id)).where(
                        EditionTranslationRunModel.book_id == book.id,
                        EditionTranslationRunModel.created_by_user_id != scope.viewer_user_id,
                    )
                )
            can_delete = not bool(other_contributions)
        if can_delete:
            can_delete = not await self._has_active_import(book_id=book.id)
        if can_delete:
            can_delete = not await self._has_active_run(book_id=book.id)
        can_translate = has_translation and await self._book_has_translatable_source(book.id)
        return ResourcePermissions(
            can_edit=can_edit,
            can_delete=can_delete,
            can_upload_edition=has_upload,
            can_translate=can_translate,
        )

    async def edition_permissions(
        self,
        scope: LibraryAccessScope,
        edition: BookEditionModel,
        file_record: EditionFileRecord | None,
    ) -> ResourcePermissions:
        has_upload = scope.has(CredentialCapability.LIBRARY_UPLOAD)
        has_translation = scope.has(CredentialCapability.TRANSLATION_USE)
        owns_edition = edition.created_by_user_id == scope.viewer_user_id
        can_edit = scope.can_manage or (
            has_upload and owns_edition and edition.creation_method is CreationMethod.UPLOADED
        )
        can_delete = scope.can_manage or (
            owns_edition
            and (
                (has_upload and edition.creation_method is CreationMethod.UPLOADED)
                or (has_translation and edition.creation_method is CreationMethod.GENERATED)
            )
        )
        if can_delete:
            can_delete = not await self._edition_has_blockers(edition.id)
        can_translate = has_translation and await self._can_translate_edition(
            scope,
            edition,
            file_record,
        )
        return ResourcePermissions(
            can_edit=can_edit,
            can_delete=can_delete,
            can_upload_edition=has_upload,
            can_translate=can_translate,
        )

    async def require_readable_book_for_upload(
        self,
        scope: LibraryAccessScope,
        book: BookModel | None,
    ) -> BookModel:
        self.require_upload_capability(scope)
        if book is None:
            raise ApplicationError("book_not_found", "Book 不存在。", status_code=404)
        return book

    async def _book_has_translatable_source(self, book_id: UUID) -> bool:
        count = await self.session.scalar(
            select(func.count(BookEditionModel.id)).where(
                BookEditionModel.book_id == book_id,
                BookEditionModel.content_role == ContentRole.SOURCE,
                BookEditionModel.status == EditionStatus.READY,
                select(EditionFileModel.id)
                .join(StoredFileModel, StoredFileModel.id == EditionFileModel.stored_file_id)
                .where(
                    EditionFileModel.edition_id == BookEditionModel.id,
                    EditionFileModel.is_current.is_(True),
                    StoredFileModel.file_format == FileFormat.TXT,
                )
                .correlate(BookEditionModel)
                .exists(),
            )
        )
        return bool(count)

    async def _can_translate_edition(
        self,
        scope: LibraryAccessScope,
        edition: BookEditionModel,
        file_record: EditionFileRecord | None,
    ) -> bool:
        if (
            edition.content_role is ContentRole.SOURCE
            and edition.status is EditionStatus.READY
            and file_record is not None
            and file_record.stored_file.file_format is FileFormat.TXT
        ):
            return True
        if (
            edition.creation_method is not CreationMethod.GENERATED
            or edition.source_edition_id is None
            or (not scope.can_manage and edition.created_by_user_id != scope.viewer_user_id)
        ):
            return False
        source = await self.editions.get(edition.source_edition_id)
        if source is None or source.status is not EditionStatus.READY:
            return False
        source_file = await self.library.get_current_edition_file(source.id)
        return bool(
            source_file is not None and source_file.stored_file.file_format is FileFormat.TXT
        )

    async def _edition_has_blockers(self, edition_id: UUID) -> bool:
        if await self.editions.dependents(edition_id):
            return True
        run_count = await self.session.scalar(
            select(func.count(EditionTranslationRunModel.id)).where(
                or_(
                    EditionTranslationRunModel.source_edition_id == edition_id,
                    EditionTranslationRunModel.supersedes_edition_id == edition_id,
                )
            )
        )
        return bool(run_count) or await self._has_active_import(edition_id=edition_id)

    async def _has_active_run(self, *, book_id: UUID) -> bool:
        count = await self.session.scalar(
            select(func.count(EditionTranslationRunModel.id)).where(
                EditionTranslationRunModel.book_id == book_id,
                EditionTranslationRunModel.status.in_(ACTIVE_TRANSLATION_RUN_STATUSES),
            )
        )
        return bool(count)

    async def _require_no_active_import(
        self,
        *,
        book_id: UUID | None = None,
        edition_id: UUID | None = None,
    ) -> None:
        if await self._has_active_import(book_id=book_id, edition_id=edition_id):
            raise ApplicationError(
                "library_import_in_progress",
                "相关上传仍在处理或等待提交，不能删除。",
                status_code=HTTPStatus.CONFLICT,
            )

    async def _has_active_import(
        self,
        *,
        book_id: UUID | None = None,
        edition_id: UUID | None = None,
    ) -> bool:
        target = []
        if book_id is not None:
            target.append(LibraryImportModel.target_book_id == book_id)
        if edition_id is not None:
            target.append(LibraryImportModel.target_edition_id == edition_id)
        if not target:
            return False
        count = await self.session.scalar(
            select(func.count(LibraryImportModel.id)).where(
                or_(*target),
                LibraryImportModel.status.in_(
                    [ImportStatus.PENDING, ImportStatus.PROCESSING, ImportStatus.READY]
                ),
            )
        )
        return bool(count)

    @staticmethod
    def _forbidden() -> None:
        raise ApplicationError(
            "library_resource_forbidden",
            "当前身份不能管理该馆藏资源。",
            status_code=HTTPStatus.FORBIDDEN,
        )
