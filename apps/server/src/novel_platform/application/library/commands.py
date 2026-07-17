from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from novel_platform.domain.editions.models import (
    ContentRole,
    EditionStatus,
    TranslationOrigin,
)
from novel_platform.domain.library.models import ImportOperation


@dataclass(frozen=True, slots=True)
class InspectImport:
    operation: ImportOperation
    filename: str | None
    submitted_media_type: str | None
    requested_text_encoding: str = "auto"
    target_book_id: UUID | None = None
    target_edition_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class CommitImport:
    series_id: UUID | None = None
    canonical_title: str | None = None
    canonical_author: str | None = None
    description: str | None = None
    book_metadata: dict[str, Any] = field(default_factory=dict)
    edition_title: str | None = None
    language: str | None = None
    content_role: ContentRole | None = None
    translation_origin: TranslationOrigin | None = None
    source_edition_id: UUID | None = None
    supersedes_edition_id: UUID | None = None
    edition_status: EditionStatus = EditionStatus.READY
    edition_metadata: dict[str, Any] = field(default_factory=dict)
    set_preferred: bool = False
    use_extracted_cover: bool | None = None
