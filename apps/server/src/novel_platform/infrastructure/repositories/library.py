from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import and_, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from novel_platform.domain.editions.models import EditionStatus
from novel_platform.infrastructure.database.models import (
    BookEditionModel,
    BookModel,
    EditionFileModel,
    LibraryImportModel,
    ReadingProgressModel,
    StoredFileModel,
    UserBookPreferenceModel,
)


@dataclass(frozen=True, slots=True)
class EditionFileRecord:
    edition_file: EditionFileModel
    stored_file: StoredFileModel
    normalized_file: StoredFileModel | None


@dataclass(frozen=True, slots=True)
class BookLibrarySummary:
    languages: list[str]
    file_formats: list[str]
    preferred_edition_id: UUID | None
    preferred_edition_title: str | None
    reading_status: str | None
    reading_progress: float
    last_read_at: datetime | None
    continue_edition_id: UUID | None
    continue_edition_title: str | None


class LibraryRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add_import(self, library_import: LibraryImportModel) -> LibraryImportModel:
        self.session.add(library_import)
        await self.session.flush()
        await self.session.refresh(library_import)
        return library_import

    async def get_import(
        self, owner_user_id: UUID, import_id: UUID, *, for_update: bool = False
    ) -> LibraryImportModel | None:
        statement = select(LibraryImportModel).where(
            LibraryImportModel.id == import_id,
            LibraryImportModel.owner_user_id == owner_user_id,
        )
        if for_update:
            statement = statement.with_for_update()
        return (await self.session.scalars(statement)).one_or_none()

    async def add_stored_file(self, stored_file: StoredFileModel) -> StoredFileModel:
        self.session.add(stored_file)
        await self.session.flush()
        await self.session.refresh(stored_file)
        return stored_file

    async def add_edition_file(self, edition_file: EditionFileModel) -> EditionFileModel:
        self.session.add(edition_file)
        await self.session.flush()
        await self.session.refresh(edition_file)
        return edition_file

    async def get_current_edition_file(self, edition_id: UUID) -> EditionFileRecord | None:
        normalized = aliased(StoredFileModel)
        statement = (
            select(EditionFileModel, StoredFileModel, normalized)
            .join(StoredFileModel, StoredFileModel.id == EditionFileModel.stored_file_id)
            .outerjoin(normalized, normalized.id == EditionFileModel.normalized_stored_file_id)
            .where(
                EditionFileModel.edition_id == edition_id,
                EditionFileModel.is_current.is_(True),
            )
        )
        row = (await self.session.execute(statement)).one_or_none()
        if row is None:
            return None
        edition_file, stored_file, normalized_file = row
        return EditionFileRecord(edition_file, stored_file, normalized_file)

    async def get_current_edition_file_for_owner(
        self, owner_user_id: UUID, edition_id: UUID
    ) -> EditionFileRecord | None:
        normalized = aliased(StoredFileModel)
        statement = (
            select(EditionFileModel, StoredFileModel, normalized)
            .join(BookEditionModel, BookEditionModel.id == EditionFileModel.edition_id)
            .join(BookModel, BookModel.id == BookEditionModel.book_id)
            .join(StoredFileModel, StoredFileModel.id == EditionFileModel.stored_file_id)
            .outerjoin(
                normalized,
                and_(
                    normalized.id == EditionFileModel.normalized_stored_file_id,
                    normalized.owner_user_id == owner_user_id,
                ),
            )
            .where(
                BookModel.owner_user_id == owner_user_id,
                StoredFileModel.owner_user_id == owner_user_id,
                EditionFileModel.edition_id == edition_id,
                EditionFileModel.is_current.is_(True),
            )
        )
        row = (await self.session.execute(statement)).one_or_none()
        if row is None:
            return None
        edition_file, stored_file, normalized_file = row
        return EditionFileRecord(edition_file, stored_file, normalized_file)

    async def book_summaries(
        self,
        *,
        owner_user_id: UUID,
        viewer_user_id: UUID | None = None,
        book_ids: list[UUID],
        readable_only: bool = False,
    ) -> dict[UUID, BookLibrarySummary]:
        if not book_ids:
            return {}
        selected = select(
            BookEditionModel.book_id,
            BookEditionModel.id,
            BookEditionModel.title,
            BookEditionModel.language,
            StoredFileModel.file_format,
        )
        if readable_only:
            statement = (
                selected.join(
                    EditionFileModel,
                    and_(
                        EditionFileModel.edition_id == BookEditionModel.id,
                        EditionFileModel.is_current.is_(True),
                    ),
                )
                .join(
                    StoredFileModel,
                    and_(
                        StoredFileModel.id == EditionFileModel.stored_file_id,
                        StoredFileModel.owner_user_id == owner_user_id,
                    ),
                )
                .where(
                    BookEditionModel.book_id.in_(book_ids),
                    BookEditionModel.status == EditionStatus.READY,
                )
            )
        else:
            statement = (
                selected.outerjoin(
                    EditionFileModel,
                    and_(
                        EditionFileModel.edition_id == BookEditionModel.id,
                        EditionFileModel.is_current.is_(True),
                    ),
                )
                .outerjoin(
                    StoredFileModel,
                    and_(
                        StoredFileModel.id == EditionFileModel.stored_file_id,
                        StoredFileModel.owner_user_id == owner_user_id,
                    ),
                )
                .where(BookEditionModel.book_id.in_(book_ids))
            )
        languages: dict[UUID, set[str]] = {book_id: set() for book_id in book_ids}
        formats: dict[UUID, set[str]] = {book_id: set() for book_id in book_ids}
        edition_titles: dict[UUID, str] = {}
        for book_id, edition_id, title, language, file_format in await self.session.execute(
            statement
        ):
            languages[book_id].add(language)
            edition_titles[edition_id] = title
            if file_format is not None:
                formats[book_id].add(file_format.value)

        preference_statement = select(
            UserBookPreferenceModel.book_id,
            UserBookPreferenceModel.preferred_edition_id,
        ).where(
            UserBookPreferenceModel.user_id == (viewer_user_id or owner_user_id),
            UserBookPreferenceModel.book_id.in_(book_ids),
        )
        preferred: dict[UUID, UUID | None] = {
            book_id: edition_id
            for book_id, edition_id in await self.session.execute(preference_statement)
        }
        progress_statement = (
            select(
                BookEditionModel.book_id,
                BookEditionModel.id,
                BookEditionModel.title,
                ReadingProgressModel.status,
                ReadingProgressModel.overall_progress,
                ReadingProgressModel.last_read_at,
            )
            .join(
                ReadingProgressModel,
                ReadingProgressModel.edition_id == BookEditionModel.id,
            )
            .where(
                ReadingProgressModel.user_id == (viewer_user_id or owner_user_id),
                BookEditionModel.book_id.in_(book_ids),
            )
            .order_by(
                ReadingProgressModel.last_read_at.desc(),
                ReadingProgressModel.edition_id.asc(),
            )
        )
        if readable_only:
            progress_statement = progress_statement.where(
                BookEditionModel.status == EditionStatus.READY,
                select(EditionFileModel.id)
                .where(
                    EditionFileModel.edition_id == BookEditionModel.id,
                    EditionFileModel.is_current.is_(True),
                )
                .correlate(BookEditionModel)
                .exists(),
            )
        latest_progress: dict[UUID, tuple[UUID, str, str, float, datetime]] = {}
        for (
            book_id,
            edition_id,
            title,
            reading_status,
            progress,
            last_read_at,
        ) in await self.session.execute(progress_statement):
            latest_progress.setdefault(
                book_id,
                (edition_id, title, reading_status.value, progress, last_read_at),
            )
        summaries: dict[UUID, BookLibrarySummary] = {}
        for book_id in book_ids:
            preferred_id = preferred.get(book_id)
            if readable_only and preferred_id not in edition_titles:
                preferred_id = None
            latest = latest_progress.get(book_id)
            summaries[book_id] = BookLibrarySummary(
                languages=sorted(languages[book_id]),
                file_formats=sorted(formats[book_id]),
                preferred_edition_id=preferred_id,
                preferred_edition_title=(
                    edition_titles.get(preferred_id) if preferred_id is not None else None
                ),
                reading_status=latest[2] if latest else None,
                reading_progress=latest[3] if latest else 0,
                last_read_at=latest[4] if latest else None,
                continue_edition_id=latest[0] if latest else None,
                continue_edition_title=latest[1] if latest else None,
            )
        return summaries

    async def next_file_revision(self, edition_id: UUID) -> int:
        statement = select(func.coalesce(func.max(EditionFileModel.revision), 0) + 1).where(
            EditionFileModel.edition_id == edition_id
        )
        return int((await self.session.scalar(statement)) or 1)

    async def edition_file_records(self, edition_id: UUID) -> list[EditionFileRecord]:
        normalized = aliased(StoredFileModel)
        statement = (
            select(EditionFileModel, StoredFileModel, normalized)
            .join(StoredFileModel, StoredFileModel.id == EditionFileModel.stored_file_id)
            .outerjoin(normalized, normalized.id == EditionFileModel.normalized_stored_file_id)
            .where(EditionFileModel.edition_id == edition_id)
            .order_by(EditionFileModel.revision)
        )
        return [
            EditionFileRecord(edition_file, stored_file, normalized_file)
            for edition_file, stored_file, normalized_file in (
                await self.session.execute(statement)
            )
        ]

    async def stored_file_is_referenced(self, stored_file_id: UUID) -> bool:
        statement = select(
            or_(
                exists().where(EditionFileModel.stored_file_id == stored_file_id),
                exists().where(EditionFileModel.normalized_stored_file_id == stored_file_id),
                exists().where(BookModel.cover_file_id == stored_file_id),
                exists().where(BookModel.cover_thumbnail_file_id == stored_file_id),
            )
        )
        return bool(await self.session.scalar(statement))

    async def get_stored_file(self, stored_file_id: UUID) -> StoredFileModel | None:
        return await self.session.get(StoredFileModel, stored_file_id)
