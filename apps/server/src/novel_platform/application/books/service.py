from datetime import UTC, datetime
from http import HTTPStatus
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from novel_platform.application.access import LibraryAccessScope
from novel_platform.application.books.commands import CreateBook, UpdateBook
from novel_platform.application.errors import ApplicationError
from novel_platform.application.library.policy import LibraryResourcePolicy
from novel_platform.domain.books.models import normalise_book_title
from novel_platform.domain.editions.models import ContentRole
from novel_platform.domain.library.models import FileFormat
from novel_platform.infrastructure.database.models import BookEditionModel, BookModel
from novel_platform.infrastructure.repositories.books import BookRepository


class BookService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repository = BookRepository(session)

    async def create(
        self,
        command: CreateBook,
        owner_user_id: UUID,
        *,
        created_by_user_id: UUID,
        commit: bool = True,
    ) -> BookModel:
        book = BookModel(
            owner_user_id=owner_user_id,
            created_by_user_id=created_by_user_id,
            canonical_title=normalise_book_title(command.canonical_title),
            canonical_author=command.canonical_author,
            description=command.description,
            extra_metadata=dict(command.metadata),
        )
        await self.repository.add(book)
        if commit:
            await self.session.commit()
        return book

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
        return await self.repository.list_page(
            owner_user_id=owner_user_id,
            limit=limit,
            offset=offset,
            query=query,
            file_format=file_format,
            language=language,
            edition_type=edition_type,
            sort=sort,
        )

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
        return await self.repository.list_readable_page(
            owner_user_id=owner_user_id,
            limit=limit,
            offset=offset,
            query=query,
            file_format=file_format,
            language=language,
            edition_type=edition_type,
            sort=sort,
        )

    async def get(self, book_id: UUID, owner_user_id: UUID) -> BookModel:
        book = await self.repository.get(book_id, owner_user_id)
        if book is None:
            raise ApplicationError(
                "book_not_found",
                "The requested book does not exist.",
                status_code=HTTPStatus.NOT_FOUND,
            )
        return book

    async def detail(
        self, book_id: UUID, owner_user_id: UUID
    ) -> tuple[BookModel, list[BookEditionModel]]:
        book = await self.get(book_id, owner_user_id)
        return book, await self.repository.editions(book_id)

    async def readable_detail(
        self, book_id: UUID, owner_user_id: UUID
    ) -> tuple[BookModel, list[BookEditionModel]]:
        book = await self.repository.get_readable(book_id, owner_user_id)
        if book is None:
            raise ApplicationError(
                "book_not_found",
                "The requested book does not exist.",
                status_code=HTTPStatus.NOT_FOUND,
            )
        return book, await self.repository.readable_editions(book_id, owner_user_id)

    async def update(
        self,
        book_id: UUID,
        owner_user_id: UUID,
        command: UpdateBook,
        *,
        scope: LibraryAccessScope,
    ) -> BookModel:
        book = await self.get(book_id, owner_user_id)
        await LibraryResourcePolicy(self.session).require_book_edit(scope, book)
        allowed = {"canonical_title", "canonical_author", "description", "metadata"}
        if not command.changes or set(command.changes) - allowed:
            raise ApplicationError(
                "validation_error",
                "至少需要提供一个有效的 Book 字段。",
                status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
            )
        if "canonical_title" in command.changes:
            title = command.changes["canonical_title"]
            if title is None:
                raise ApplicationError(
                    "validation_error",
                    "书名不能为空。",
                    status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
                )
            book.canonical_title = normalise_book_title(title)
        if "canonical_author" in command.changes:
            book.canonical_author = command.changes["canonical_author"]
        if "description" in command.changes:
            book.description = command.changes["description"]
        if "metadata" in command.changes:
            metadata = command.changes["metadata"]
            if metadata is None:
                raise ApplicationError(
                    "validation_error",
                    "metadata 不能为空。",
                    status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
                )
            book.extra_metadata = dict(metadata)
        book.updated_at = datetime.now(UTC)
        await self.session.commit()
        return book
