from datetime import UTC, datetime
from http import HTTPStatus
from typing import Any, ClassVar
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from novel_platform.application.editions.commands import CreateEdition, UpdateEdition
from novel_platform.application.errors import ApplicationError
from novel_platform.domain.editions.models import ContentRole, validate_edition
from novel_platform.infrastructure.database.models import BookEditionModel
from novel_platform.infrastructure.repositories.books import BookRepository
from novel_platform.infrastructure.repositories.editions import EditionRepository


class EditionService:
    _PATCHABLE_FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "title",
            "status",
            "source_edition_id",
            "supersedes_edition_id",
            "metadata",
        }
    )

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.books = BookRepository(session)
        self.editions = EditionRepository(session)

    async def _require_book(self, book_id: UUID, owner_user_id: UUID) -> None:
        if await self.books.get(book_id, owner_user_id) is None:
            raise ApplicationError(
                "book_not_found",
                "The requested book does not exist.",
                status_code=HTTPStatus.NOT_FOUND,
            )

    async def _validate_relationships(
        self,
        *,
        book_id: UUID,
        owner_user_id: UUID,
        source_edition_id: UUID | None,
        supersedes_edition_id: UUID | None,
    ) -> None:
        if source_edition_id is not None:
            source = await self.editions.get_for_owner(owner_user_id, source_edition_id)
            if source is None:
                raise ApplicationError(
                    "edition_not_found",
                    "The referenced source edition is not visible.",
                    status_code=HTTPStatus.NOT_FOUND,
                )
            if source.book_id != book_id:
                raise ApplicationError(
                    "cross_book_edition_reference",
                    "The referenced source edition belongs to another book.",
                    status_code=HTTPStatus.CONFLICT,
                )
            if source.content_role is not ContentRole.SOURCE:
                raise ApplicationError(
                    "source_edition_must_be_source",
                    "The referenced source edition must have the source role.",
                    status_code=HTTPStatus.CONFLICT,
                )

        if supersedes_edition_id is not None:
            superseded = await self.editions.get_for_owner(owner_user_id, supersedes_edition_id)
            if superseded is None:
                raise ApplicationError(
                    "edition_not_found",
                    "The superseded edition is not visible.",
                    status_code=HTTPStatus.NOT_FOUND,
                )
            if superseded.book_id != book_id:
                raise ApplicationError(
                    "cross_book_edition_reference",
                    "The superseded edition belongs to another book.",
                    status_code=HTTPStatus.CONFLICT,
                )

    async def create(
        self,
        book_id: UUID,
        owner_user_id: UUID,
        command: CreateEdition,
        *,
        created_by_user_id: UUID,
        commit: bool = True,
    ) -> BookEditionModel:
        await self._require_book(book_id, owner_user_id)
        edition_id = uuid4()
        title, language = validate_edition(
            edition_id=edition_id,
            title=command.title,
            language=command.language,
            content_role=command.content_role,
            translation_origin=command.translation_origin,
            source_edition_id=command.source_edition_id,
            supersedes_edition_id=command.supersedes_edition_id,
            revision=command.revision,
        )
        await self._validate_relationships(
            book_id=book_id,
            owner_user_id=owner_user_id,
            source_edition_id=command.source_edition_id,
            supersedes_edition_id=command.supersedes_edition_id,
        )
        edition = BookEditionModel(
            id=edition_id,
            book_id=book_id,
            created_by_user_id=created_by_user_id,
            title=title,
            language=language,
            content_role=command.content_role,
            translation_origin=command.translation_origin,
            creation_method=command.creation_method,
            source_edition_id=command.source_edition_id,
            supersedes_edition_id=command.supersedes_edition_id,
            status=command.status,
            revision=command.revision,
            extra_metadata=dict(command.metadata),
        )
        await self.editions.add(edition)
        if commit:
            await self.session.commit()
        return edition

    async def get(
        self,
        book_id: UUID,
        owner_user_id: UUID,
        edition_id: UUID,
        *,
        for_update: bool = False,
    ) -> BookEditionModel:
        await self._require_book(book_id, owner_user_id)
        edition = await self.editions.get_for_book(
            book_id,
            edition_id,
            for_update=for_update,
        )
        if edition is None:
            raise ApplicationError(
                "edition_not_found",
                "The requested edition does not exist for this book.",
                status_code=HTTPStatus.NOT_FOUND,
            )
        return edition

    async def get_readable(
        self,
        book_id: UUID,
        owner_user_id: UUID,
        edition_id: UUID,
    ) -> BookEditionModel:
        edition = await self.editions.get_readable(owner_user_id, edition_id)
        if edition is None or edition.book_id != book_id:
            raise ApplicationError(
                "edition_not_found",
                "The requested edition does not exist for this book.",
                status_code=HTTPStatus.NOT_FOUND,
            )
        return edition

    async def update(
        self,
        book_id: UUID,
        owner_user_id: UUID,
        edition_id: UUID,
        command: UpdateEdition,
    ) -> BookEditionModel:
        edition = await self.get(book_id, owner_user_id, edition_id)
        unexpected = set(command.changes) - self._PATCHABLE_FIELDS
        if unexpected:
            raise ApplicationError(
                "immutable_edition_field",
                "One or more edition fields cannot be changed.",
                status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
                details={"fields": sorted(unexpected)},
            )

        candidate: dict[str, Any] = {
            "title": command.changes.get("title", edition.title),
            "status": command.changes.get("status", edition.status),
            "source_edition_id": command.changes.get(
                "source_edition_id", edition.source_edition_id
            ),
            "supersedes_edition_id": command.changes.get(
                "supersedes_edition_id", edition.supersedes_edition_id
            ),
            "metadata": command.changes.get("metadata", edition.extra_metadata),
        }
        if candidate["title"] is None or candidate["metadata"] is None:
            raise ApplicationError(
                "validation_error",
                "Title and metadata cannot be null.",
                status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
            )
        title, _ = validate_edition(
            edition_id=edition.id,
            title=candidate["title"],
            language=edition.language,
            content_role=edition.content_role,
            translation_origin=edition.translation_origin,
            source_edition_id=candidate["source_edition_id"],
            supersedes_edition_id=candidate["supersedes_edition_id"],
            revision=edition.revision,
        )
        await self._validate_relationships(
            book_id=book_id,
            owner_user_id=owner_user_id,
            source_edition_id=candidate["source_edition_id"],
            supersedes_edition_id=candidate["supersedes_edition_id"],
        )
        edition.title = title
        edition.status = candidate["status"]
        edition.source_edition_id = candidate["source_edition_id"]
        edition.supersedes_edition_id = candidate["supersedes_edition_id"]
        edition.extra_metadata = dict(candidate["metadata"])
        edition.updated_at = datetime.now(UTC)
        await self.session.flush()
        await self.session.commit()
        await self.session.refresh(edition)
        return edition
