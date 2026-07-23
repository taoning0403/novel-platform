from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from novel_platform.api.schemas import (
    BookDetailResponse,
    BookListItem,
    BookResponse,
    EditionResponse,
)
from novel_platform.api.serializers import (
    book_detail_response,
    book_list_item,
    book_response,
    edition_response,
)
from novel_platform.application.access import LibraryAccessScope
from novel_platform.application.errors import ApplicationError
from novel_platform.application.library.policy import LibraryResourcePolicy
from novel_platform.infrastructure.database.models import (
    BookEditionModel,
    BookModel,
    ReadingProgressModel,
)
from novel_platform.infrastructure.repositories.library import (
    BookLibrarySummary,
    EditionFileRecord,
)
from novel_platform.infrastructure.repositories.users import UserRepository


class LibraryResponseBuilder:
    def __init__(self, session: AsyncSession, scope: LibraryAccessScope) -> None:
        self.scope = scope
        self.policy = LibraryResourcePolicy(session)
        self.users = UserRepository(session)
        self._display_names: dict[UUID, str] = {}

    async def book(self, book: BookModel) -> BookResponse:
        await self._load_names({book.created_by_user_id})
        return book_response(
            book,
            contributor_display_name=self._name(book.created_by_user_id),
            permissions=await self.policy.book_permissions(self.scope, book),
        )

    async def book_list_item(
        self,
        book: BookModel,
        edition_count: int,
        summary: BookLibrarySummary | None = None,
        *,
        series_id: UUID | None = None,
        series_name: str | None = None,
        series_position: int | None = None,
    ) -> BookListItem:
        await self._load_names({book.created_by_user_id})
        return book_list_item(
            book,
            edition_count,
            summary,
            contributor_display_name=self._name(book.created_by_user_id),
            permissions=await self.policy.book_permissions(self.scope, book),
            series_id=series_id,
            series_name=series_name,
            series_position=series_position,
        )

    async def edition(
        self,
        edition: BookEditionModel,
        file_record: EditionFileRecord | None = None,
        progress: ReadingProgressModel | None = None,
    ) -> EditionResponse:
        await self._load_names({edition.created_by_user_id})
        return edition_response(
            edition,
            file_record,
            progress,
            contributor_display_name=self._name(edition.created_by_user_id),
            permissions=await self.policy.edition_permissions(
                self.scope,
                edition,
                file_record,
            ),
            include_download=self.scope.can_manage,
        )

    async def detail(
        self,
        book: BookModel,
        editions: list[BookEditionModel],
        files: dict[UUID, EditionFileRecord],
        progresses: dict[UUID, ReadingProgressModel],
    ) -> BookDetailResponse:
        await self._load_names(
            {book.created_by_user_id, *(edition.created_by_user_id for edition in editions)}
        )
        return book_detail_response(
            book,
            editions,
            files,
            progresses,
            contributor_display_name=self._name(book.created_by_user_id),
            permissions=await self.policy.book_permissions(self.scope, book),
            edition_contributors={
                edition.id: self._name(edition.created_by_user_id) for edition in editions
            },
            edition_permissions={
                edition.id: await self.policy.edition_permissions(
                    self.scope,
                    edition,
                    files.get(edition.id),
                )
                for edition in editions
            },
            include_download=self.scope.can_manage,
        )

    async def _load_names(self, user_ids: set[UUID]) -> None:
        missing = user_ids - self._display_names.keys()
        if missing:
            self._display_names.update(await self.users.display_names(missing))
        if missing - self._display_names.keys():
            raise ApplicationError(
                "contributor_integrity_error",
                "馆藏贡献者记录不完整。",
                status_code=500,
            )

    def _name(self, user_id: UUID) -> str:
        return self._display_names[user_id]
