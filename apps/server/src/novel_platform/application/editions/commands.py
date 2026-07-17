from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from novel_platform.domain.editions.models import (
    ContentRole,
    CreationMethod,
    EditionStatus,
    TranslationOrigin,
)


@dataclass(frozen=True, slots=True)
class CreateEdition:
    title: str
    language: str
    content_role: ContentRole
    translation_origin: TranslationOrigin | None
    creation_method: CreationMethod
    source_edition_id: UUID | None = None
    supersedes_edition_id: UUID | None = None
    status: EditionStatus = EditionStatus.DRAFT
    revision: int = 1
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class UpdateEdition:
    changes: dict[str, Any]
