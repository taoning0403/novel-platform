from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class CreateBook:
    canonical_title: str
    canonical_author: str | None = None
    description: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class UpdateBook:
    changes: dict[str, Any]
