import os
from datetime import UTC, datetime
from functools import partial
from pathlib import PurePath
from uuid import UUID

from anyio import to_thread
from sqlalchemy.ext.asyncio import AsyncSession

from novel_platform.application.editions.commands import CreateEdition
from novel_platform.application.editions.service import EditionService
from novel_platform.application.errors import ApplicationError
from novel_platform.application.library.filenames import sanitize_filename
from novel_platform.application.library.storage import FileStorage, StorageError
from novel_platform.application.library.text import normalize_text
from novel_platform.config import Settings
from novel_platform.domain.editions.models import (
    ContentRole,
    CreationMethod,
    EditionStatus,
    TranslationOrigin,
)
from novel_platform.domain.library.models import FileFormat, StoredFilePurpose
from novel_platform.domain.translations.models import TranslationRunStatus
from novel_platform.infrastructure.database.models import (
    BookEditionModel,
    EditionFileModel,
    StoredFileModel,
)
from novel_platform.infrastructure.integrations.linguaspindle import (
    LinguaSpindleGateway,
    RemoteArtifact,
)
from novel_platform.infrastructure.repositories.library import LibraryRepository
from novel_platform.infrastructure.repositories.translation_runs import TranslationRunRepository


class GeneratedTranslationIngestionService:
    def __init__(
        self,
        session: AsyncSession,
        storage: FileStorage,
        settings: Settings,
        client: LinguaSpindleGateway,
    ) -> None:
        self.session = session
        self.storage = storage
        self.settings = settings
        self.client = client
        self.runs = TranslationRunRepository(session)
        self.library = LibraryRepository(session)
        self.editions = EditionService(session)

    async def ingest(
        self,
        *,
        owner_user_id: UUID,
        run_id: UUID,
        artifact: RemoteArtifact,
        request_id: str,
    ) -> BookEditionModel:
        run = await self.runs.get(owner_user_id, run_id)
        if run is None:
            raise ApplicationError("translation_run_not_found", "翻译任务不存在。", status_code=404)
        self._validate_artifact(run.remote_project_id, run.remote_job_id, artifact)

        source_key = await to_thread.run_sync(self.storage.allocate_temporary)
        normalized_key: str | None = None
        moved: list[tuple[str, str]] = []
        try:
            source_path = self.storage.temporary_path(source_key)
            with source_path.open("wb") as destination:
                downloaded = await self.client.download_artifact(
                    artifact,
                    destination,
                    request_id=request_id,
                    max_bytes=self.settings.linguaspindle_max_download_bytes,
                )
                destination.flush()
                os.fsync(destination.fileno())
            if (
                downloaded.size == 0
                or downloaded.size != artifact.size
                or downloaded.sha256 != artifact.checksum
            ):
                raise ApplicationError(
                    "translation_artifact_integrity_error",
                    "翻译产物完整性校验失败。",
                    status_code=502,
                )

            normalized_key = await to_thread.run_sync(self.storage.allocate_temporary)
            normalized_path = self.storage.temporary_path(normalized_key)
            parsed = await to_thread.run_sync(
                partial(
                    normalize_text,
                    source_path,
                    normalized_path,
                    requested_encoding="auto",
                    inferred_title=PurePath(artifact.filename).stem or "translated",
                )
            )
            normalized_size = (await to_thread.run_sync(normalized_path.stat)).st_size
            normalized_sha256 = await to_thread.run_sync(
                self.storage.calculate_temporary_checksum, normalized_key
            )

            locked = await self.runs.get(owner_user_id, run_id, for_update=True)
            if locked is None:
                raise ApplicationError(
                    "translation_run_not_found", "翻译任务不存在。", status_code=404
                )
            if locked.generated_edition_id is not None:
                existing = await self.session.get(BookEditionModel, locked.generated_edition_id)
                if existing is None:
                    raise ApplicationError(
                        "translation_generated_edition_missing",
                        "翻译任务关联的版本不存在。",
                        status_code=409,
                    )
                return existing
            if locked.status is not TranslationRunStatus.INGESTING:
                raise ApplicationError(
                    "translation_run_state_conflict",
                    "翻译任务当前不能导入产物。",
                    status_code=409,
                )

            source_storage_key = await to_thread.run_sync(self.storage.commit_temporary, source_key)
            moved.append((source_key, source_storage_key))
            normalized_storage_key = await to_thread.run_sync(
                self.storage.commit_temporary, normalized_key
            )
            moved.append((normalized_key, normalized_storage_key))

            source_file = await self.library.add_stored_file(
                StoredFileModel(
                    owner_user_id=locked.library_owner_user_id,
                    created_by_user_id=locked.created_by_user_id,
                    storage_key=source_storage_key,
                    original_filename=sanitize_filename(artifact.filename),
                    media_type="text/plain",
                    file_format=FileFormat.TXT,
                    purpose=StoredFilePurpose.EDITION_SOURCE,
                    size_bytes=artifact.size,
                    sha256=artifact.checksum,
                )
            )
            normalized_file = await self.library.add_stored_file(
                StoredFileModel(
                    owner_user_id=locked.library_owner_user_id,
                    created_by_user_id=locked.created_by_user_id,
                    storage_key=normalized_storage_key,
                    original_filename=sanitize_filename(
                        f"{PurePath(artifact.filename).stem or 'translated'}.utf8.txt"
                    ),
                    media_type="text/plain; charset=utf-8",
                    file_format=FileFormat.TXT,
                    purpose=StoredFilePurpose.NORMALIZED_TEXT,
                    size_bytes=normalized_size,
                    sha256=normalized_sha256,
                )
            )
            edition = await self.editions.create(
                locked.book_id,
                locked.library_owner_user_id,
                CreateEdition(
                    title=locked.edition_title,
                    language=locked.target_language,
                    content_role=ContentRole.TRANSLATION,
                    translation_origin=TranslationOrigin.AI,
                    creation_method=CreationMethod.GENERATED,
                    source_edition_id=locked.source_edition_id,
                    supersedes_edition_id=locked.supersedes_edition_id,
                    status=EditionStatus.DRAFT,
                    metadata={
                        "generated_by": "linguaspindle",
                        "pipeline": "novel_txt_v1",
                    },
                ),
                created_by_user_id=locked.created_by_user_id,
                commit=False,
            )
            await self.library.add_edition_file(
                EditionFileModel(
                    edition_id=edition.id,
                    stored_file_id=source_file.id,
                    normalized_stored_file_id=normalized_file.id,
                    revision=1,
                    is_current=True,
                    text_encoding=parsed.encoding,
                    content_item_count=parsed.content_item_count,
                    extracted_metadata=dict(parsed.metadata),
                )
            )
            now = datetime.now(UTC)
            locked.generated_edition_id = edition.id
            locked.status = TranslationRunStatus.SUCCEEDED
            locked.progress = 1
            locked.error_code = None
            locked.error_message = None
            locked.error_details = {}
            locked.completed_at = now
            locked.last_synced_at = now
            locked.updated_at = now
            await self.session.commit()
            return edition
        except StorageError as exc:
            await self.session.rollback()
            await self._restore(moved)
            raise ApplicationError(
                "file_storage_error", "翻译产物存储失败，请稍后重试。", status_code=500
            ) from exc
        except Exception:
            await self.session.rollback()
            await self._restore(moved)
            raise
        finally:
            for key in (source_key, normalized_key):
                if key is None:
                    continue
                try:
                    if await to_thread.run_sync(self.storage.temporary_exists, key):
                        await to_thread.run_sync(self.storage.delete_temporary, key)
                except StorageError:
                    pass

    @staticmethod
    def _validate_artifact(
        project_id: str | None,
        job_id: str | None,
        artifact: RemoteArtifact,
    ) -> None:
        if (
            project_id is None
            or job_id is None
            or artifact.project_id != project_id
            or artifact.job_id != job_id
            or artifact.kind != "novel_export_txt"
            or artifact.media_type.split(";", 1)[0].strip().lower() != "text/plain"
            or PurePath(artifact.filename).suffix.lower() != ".txt"
            or artifact.size <= 0
        ):
            raise ApplicationError(
                "translation_artifact_invalid",
                "翻译产物与任务不匹配。",
                status_code=502,
            )

    async def _restore(self, moved: list[tuple[str, str]]) -> None:
        for temporary_key, storage_key in reversed(moved):
            try:
                await to_thread.run_sync(self.storage.restore_committed, storage_key, temporary_key)
            except StorageError:
                pass
