from uuid import UUID

from sqlalchemy import Select, and_, case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from novel_platform.domain.editions.models import ContentRole, CreationMethod, EditionStatus
from novel_platform.domain.library.models import FileFormat
from novel_platform.infrastructure.database.models import (
    BookEditionModel,
    BookModel,
    EditionFileModel,
    StoredFileModel,
)


class BookRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add(self, book: BookModel) -> BookModel:
        self.session.add(book)
        await self.session.flush()
        await self.session.refresh(book)
        return book

    async def get(self, book_id: UUID, owner_user_id: UUID) -> BookModel | None:
        statement = select(BookModel).where(
            BookModel.id == book_id,
            BookModel.owner_user_id == owner_user_id,
        )
        return (await self.session.scalars(statement)).one_or_none()

    async def list_page(
        self,
        *,
        owner_user_id: UUID,
        limit: int,
        offset: int,
        query: str | None = None,
        file_format: FileFormat | None = None,
        language: str | None = None,
        edition_type: ContentRole | None = None,
        sort: str = "updated_desc",
    ) -> list[tuple[BookModel, int]]:
        statement: Select[tuple[BookModel, int]] = (
            select(BookModel, func.count(BookEditionModel.id).label("edition_count"))
            .outerjoin(BookEditionModel, BookEditionModel.book_id == BookModel.id)
            .where(BookModel.owner_user_id == owner_user_id)
            .group_by(BookModel.id)
        )
        if query:
            pattern = f"%{query.strip()}%"
            statement = statement.where(
                or_(
                    BookModel.canonical_title.ilike(pattern),
                    BookModel.canonical_author.ilike(pattern),
                )
            )
        if language:
            statement = statement.where(
                select(BookEditionModel.id)
                .where(
                    BookEditionModel.book_id == BookModel.id,
                    BookEditionModel.language == language,
                )
                .correlate(BookModel)
                .exists()
            )
        if edition_type:
            statement = statement.where(
                select(BookEditionModel.id)
                .where(
                    BookEditionModel.book_id == BookModel.id,
                    BookEditionModel.content_role == edition_type,
                )
                .correlate(BookModel)
                .exists()
            )
        if file_format:
            statement = statement.where(
                select(EditionFileModel.id)
                .join(BookEditionModel, BookEditionModel.id == EditionFileModel.edition_id)
                .join(StoredFileModel, StoredFileModel.id == EditionFileModel.stored_file_id)
                .where(
                    BookEditionModel.book_id == BookModel.id,
                    EditionFileModel.is_current.is_(True),
                    StoredFileModel.owner_user_id == owner_user_id,
                    StoredFileModel.file_format == file_format,
                )
                .correlate(BookModel)
                .exists()
            )
        if sort == "title_asc":
            statement = statement.order_by(BookModel.canonical_title.asc(), BookModel.id.asc())
        elif sort == "created_desc":
            statement = statement.order_by(BookModel.created_at.desc(), BookModel.id.asc())
        else:
            statement = statement.order_by(BookModel.updated_at.desc(), BookModel.id.asc())
        statement = statement.limit(limit).offset(offset)
        rows = (await self.session.execute(statement)).all()
        return [(book, count) for book, count in rows]

    async def editions(self, book_id: UUID) -> list[BookEditionModel]:
        role_order = case((BookEditionModel.content_role == ContentRole.SOURCE, 0), else_=1)
        statement = (
            select(BookEditionModel)
            .where(BookEditionModel.book_id == book_id)
            .order_by(role_order, BookEditionModel.created_at.asc(), BookEditionModel.id.asc())
        )
        return list((await self.session.scalars(statement)).all())

    async def get_readable(self, book_id: UUID, owner_user_id: UUID) -> BookModel | None:
        statement = select(BookModel).where(
            BookModel.id == book_id,
            BookModel.owner_user_id == owner_user_id,
            select(BookEditionModel.id)
            .join(EditionFileModel, EditionFileModel.edition_id == BookEditionModel.id)
            .join(StoredFileModel, StoredFileModel.id == EditionFileModel.stored_file_id)
            .where(
                BookEditionModel.book_id == BookModel.id,
                BookEditionModel.status == EditionStatus.READY,
                EditionFileModel.is_current.is_(True),
                StoredFileModel.owner_user_id == owner_user_id,
            )
            .correlate(BookModel)
            .exists(),
        )
        return (await self.session.scalars(statement)).one_or_none()

    async def list_readable_page(
        self,
        *,
        owner_user_id: UUID,
        limit: int,
        offset: int,
        query: str | None = None,
        file_format: FileFormat | None = None,
        language: str | None = None,
        edition_type: ContentRole | None = None,
        sort: str = "updated_desc",
    ) -> list[tuple[BookModel, int]]:
        statement: Select[tuple[BookModel, int]] = (
            select(BookModel, func.count(BookEditionModel.id).label("edition_count"))
            .join(
                BookEditionModel,
                (BookEditionModel.book_id == BookModel.id)
                & (BookEditionModel.status == EditionStatus.READY),
            )
            .join(
                EditionFileModel,
                (EditionFileModel.edition_id == BookEditionModel.id)
                & EditionFileModel.is_current.is_(True),
            )
            .join(StoredFileModel, StoredFileModel.id == EditionFileModel.stored_file_id)
            .where(
                BookModel.owner_user_id == owner_user_id,
                StoredFileModel.owner_user_id == owner_user_id,
            )
            .group_by(BookModel.id)
        )
        if query:
            pattern = f"%{query.strip()}%"
            statement = statement.where(
                or_(
                    BookModel.canonical_title.ilike(pattern),
                    BookModel.canonical_author.ilike(pattern),
                )
            )
        if language:
            statement = statement.where(
                select(BookEditionModel.id)
                .join(EditionFileModel, EditionFileModel.edition_id == BookEditionModel.id)
                .where(
                    BookEditionModel.book_id == BookModel.id,
                    BookEditionModel.status == EditionStatus.READY,
                    BookEditionModel.language == language,
                    EditionFileModel.is_current.is_(True),
                )
                .correlate(BookModel)
                .exists()
            )
        if edition_type:
            statement = statement.where(
                select(BookEditionModel.id)
                .join(EditionFileModel, EditionFileModel.edition_id == BookEditionModel.id)
                .where(
                    BookEditionModel.book_id == BookModel.id,
                    BookEditionModel.status == EditionStatus.READY,
                    BookEditionModel.content_role == edition_type,
                    EditionFileModel.is_current.is_(True),
                )
                .correlate(BookModel)
                .exists()
            )
        if file_format:
            statement = statement.where(
                select(EditionFileModel.id)
                .join(BookEditionModel, BookEditionModel.id == EditionFileModel.edition_id)
                .join(StoredFileModel, StoredFileModel.id == EditionFileModel.stored_file_id)
                .where(
                    BookEditionModel.book_id == BookModel.id,
                    BookEditionModel.status == EditionStatus.READY,
                    EditionFileModel.is_current.is_(True),
                    StoredFileModel.owner_user_id == owner_user_id,
                    StoredFileModel.file_format == file_format,
                )
                .correlate(BookModel)
                .exists()
            )
        if sort == "title_asc":
            statement = statement.order_by(BookModel.canonical_title.asc(), BookModel.id.asc())
        elif sort == "created_desc":
            statement = statement.order_by(BookModel.created_at.desc(), BookModel.id.asc())
        else:
            statement = statement.order_by(BookModel.updated_at.desc(), BookModel.id.asc())
        rows = (await self.session.execute(statement.limit(limit).offset(offset))).all()
        return [(book, count) for book, count in rows]

    async def readable_editions(self, book_id: UUID, owner_user_id: UUID) -> list[BookEditionModel]:
        role_order = case((BookEditionModel.content_role == ContentRole.SOURCE, 0), else_=1)
        statement = (
            select(BookEditionModel)
            .join(EditionFileModel, EditionFileModel.edition_id == BookEditionModel.id)
            .join(StoredFileModel, StoredFileModel.id == EditionFileModel.stored_file_id)
            .where(
                BookEditionModel.book_id == book_id,
                BookEditionModel.status == EditionStatus.READY,
                EditionFileModel.is_current.is_(True),
                StoredFileModel.owner_user_id == owner_user_id,
            )
            .order_by(role_order, BookEditionModel.created_at.asc(), BookEditionModel.id.asc())
        )
        return list((await self.session.scalars(statement)).all())

    async def visible_editions(
        self,
        book_id: UUID,
        owner_user_id: UUID,
        viewer_user_id: UUID,
    ) -> list[BookEditionModel]:
        """List ready editions plus generated drafts created by this viewer."""
        role_order = case((BookEditionModel.content_role == ContentRole.SOURCE, 0), else_=1)
        statement = (
            select(BookEditionModel)
            .join(EditionFileModel, EditionFileModel.edition_id == BookEditionModel.id)
            .join(StoredFileModel, StoredFileModel.id == EditionFileModel.stored_file_id)
            .where(
                BookEditionModel.book_id == book_id,
                or_(
                    BookEditionModel.status == EditionStatus.READY,
                    and_(
                        BookEditionModel.status == EditionStatus.DRAFT,
                        BookEditionModel.creation_method == CreationMethod.GENERATED,
                        BookEditionModel.created_by_user_id == viewer_user_id,
                    ),
                ),
                EditionFileModel.is_current.is_(True),
                StoredFileModel.owner_user_id == owner_user_id,
            )
            .order_by(role_order, BookEditionModel.created_at.asc(), BookEditionModel.id.asc())
        )
        return list((await self.session.scalars(statement)).all())
