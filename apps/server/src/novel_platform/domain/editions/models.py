from enum import StrEnum
from uuid import UUID

from novel_platform.domain.errors import DomainRuleViolation


class ContentRole(StrEnum):
    SOURCE = "source"
    TRANSLATION = "translation"


class TranslationOrigin(StrEnum):
    AI = "ai"
    HUMAN = "human"
    MIXED = "mixed"
    UNKNOWN = "unknown"


class CreationMethod(StrEnum):
    UPLOADED = "uploaded"
    GENERATED = "generated"
    EDITED = "edited"
    CONVERTED = "converted"


class EditionStatus(StrEnum):
    DRAFT = "draft"
    READY = "ready"
    ARCHIVED = "archived"


def validate_edition(
    *,
    edition_id: UUID,
    title: str,
    language: str,
    content_role: ContentRole,
    translation_origin: TranslationOrigin | None,
    source_edition_id: UUID | None,
    supersedes_edition_id: UUID | None,
    revision: int,
) -> tuple[str, str]:
    normalised_title = title.strip()
    normalised_language = language.strip()
    if not normalised_title:
        raise DomainRuleViolation("invalid_edition_title", "Edition title cannot be empty.")
    if not normalised_language:
        raise DomainRuleViolation("invalid_edition_language", "Edition language cannot be empty.")
    if revision < 1:
        raise DomainRuleViolation("invalid_revision", "Edition revision must be at least 1.")
    if source_edition_id == edition_id or supersedes_edition_id == edition_id:
        raise DomainRuleViolation(
            "edition_cannot_reference_itself",
            "An edition cannot reference itself.",
        )
    if content_role is ContentRole.SOURCE:
        if translation_origin is not None:
            raise DomainRuleViolation(
                "invalid_translation_origin",
                "A source edition cannot have a translation origin.",
            )
        if source_edition_id is not None:
            raise DomainRuleViolation(
                "invalid_edition_role",
                "A source edition cannot reference another source edition.",
            )
    elif translation_origin is None:
        raise DomainRuleViolation(
            "invalid_translation_origin",
            "A translation edition must have a translation origin.",
        )
    return normalised_title, normalised_language
