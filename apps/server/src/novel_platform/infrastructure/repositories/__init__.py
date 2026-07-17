from novel_platform.infrastructure.repositories.auth import AuthRepository
from novel_platform.infrastructure.repositories.books import BookRepository
from novel_platform.infrastructure.repositories.editions import EditionRepository
from novel_platform.infrastructure.repositories.preferences import PreferenceRepository
from novel_platform.infrastructure.repositories.users import UserRepository

__all__ = [
    "AuthRepository",
    "BookRepository",
    "EditionRepository",
    "PreferenceRepository",
    "UserRepository",
]
