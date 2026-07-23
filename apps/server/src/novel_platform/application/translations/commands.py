from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True, slots=True)
class CreateTranslationRun:
    target_language: str
    edition_title: str
    client_request_id: UUID
    supersedes_edition_id: UUID | None = None
