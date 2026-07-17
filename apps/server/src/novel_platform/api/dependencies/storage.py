from functools import lru_cache
from typing import Annotated

from fastapi import Depends

from novel_platform.application.library.storage import FileStorage
from novel_platform.config import get_settings
from novel_platform.infrastructure.storage.local import LocalFileStorage


@lru_cache
def get_file_storage() -> LocalFileStorage:
    return LocalFileStorage(get_settings().library_storage_root)


FileStorageDependency = Annotated[FileStorage, Depends(get_file_storage)]
