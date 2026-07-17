from datetime import UTC, datetime
from http import HTTPStatus
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from novel_platform.application.errors import ApplicationError
from novel_platform.infrastructure.database.models import UserBookPreferenceModel
from novel_platform.infrastructure.repositories.books import BookRepository
from novel_platform.infrastructure.repositories.editions import EditionRepository
from novel_platform.infrastructure.repositories.preferences import PreferenceRepository


class PreferenceService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.books = BookRepository(session)
        self.editions = EditionRepository(session)
        self.preferences = PreferenceRepository(session)

    async def get(
        self,
        user_id: UUID,
        owner_user_id: UUID,
        book_id: UUID,
        *,
        readable_only: bool,
    ) -> UserBookPreferenceModel | None:
        await self._require_book(owner_user_id, book_id, readable_only=readable_only)
        return await self.preferences.get(user_id, book_id)

    async def update(
        self,
        user_id: UUID,
        owner_user_id: UUID,
        book_id: UUID,
        changes: dict[str, Any],
        *,
        readable_only: bool,
        commit: bool = True,
    ) -> UserBookPreferenceModel:
        await self._require_book(owner_user_id, book_id, readable_only=readable_only)
        allowed = {"preferred_edition_id", "last_opened_edition_id"}
        if not changes or set(changes) - allowed:
            raise ApplicationError(
                "validation_error", "至少需要提供一个有效的偏好字段。", status_code=422
            )
        for field_name, error_code in (
            ("preferred_edition_id", "invalid_preferred_edition"),
            ("last_opened_edition_id", "invalid_last_opened_edition"),
        ):
            edition_id = changes.get(field_name)
            if field_name in changes and edition_id is not None:
                edition = (
                    await self.editions.get_readable(owner_user_id, edition_id)
                    if readable_only
                    else await self.editions.get_for_owner(owner_user_id, edition_id)
                )
                if edition is None or edition.book_id != book_id:
                    raise ApplicationError(
                        error_code,
                        "所选 Edition 不属于当前 Book。",
                        status_code=HTTPStatus.CONFLICT,
                    )
        now = datetime.now(UTC)
        preference = await self.preferences.get(user_id, book_id)
        if preference is None:
            preference = await self.preferences.ensure(
                UserBookPreferenceModel(
                    user_id=user_id,
                    book_id=book_id,
                    preferred_edition_id=None,
                    last_opened_edition_id=None,
                    created_at=now,
                    updated_at=now,
                )
            )
        for field_name, value in changes.items():
            setattr(preference, field_name, value)
        preference.updated_at = now
        if commit:
            await self.session.commit()
        return preference

    async def _require_book(
        self, owner_user_id: UUID, book_id: UUID, *, readable_only: bool
    ) -> None:
        book = (
            await self.books.get_readable(book_id, owner_user_id)
            if readable_only
            else await self.books.get(book_id, owner_user_id)
        )
        if book is None:
            raise ApplicationError(
                "book_not_found", "Book 不存在。", status_code=HTTPStatus.NOT_FOUND
            )
