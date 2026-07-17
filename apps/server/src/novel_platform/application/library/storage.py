from collections.abc import Collection
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import BinaryIO, Protocol


class StorageError(Exception):
    """Base class for safe, non-path-bearing storage failures."""


class StorageLimitExceeded(StorageError):
    pass


class StorageObjectNotFound(StorageError):
    pass


class StorageIntegrityError(StorageError):
    pass


@dataclass(frozen=True, slots=True)
class TemporaryFile:
    key: str
    size_bytes: int
    sha256: str


class FileStorage(Protocol):
    @property
    def root(self) -> Path: ...

    @property
    def temporary_directory(self) -> Path: ...

    def initialize(self) -> None: ...

    def write_temporary(self, stream: BinaryIO, *, max_bytes: int) -> TemporaryFile: ...

    def write_temporary_bytes(self, content: bytes, *, max_bytes: int) -> TemporaryFile: ...

    def allocate_temporary(self) -> str: ...

    def temporary_path(self, key: str) -> Path: ...

    def commit_temporary(self, key: str) -> str: ...

    def restore_committed(self, storage_key: str, temporary_key: str) -> None: ...

    def open_file(self, storage_key: str) -> BinaryIO: ...

    def open_temporary(self, key: str) -> BinaryIO: ...

    def delete_file(self, storage_key: str) -> None: ...

    def delete_temporary(self, key: str) -> None: ...

    def exists(self, storage_key: str) -> bool: ...

    def temporary_exists(self, key: str) -> bool: ...

    def calculate_checksum(self, storage_key: str) -> str: ...

    def calculate_temporary_checksum(self, key: str) -> str: ...

    def cleanup_temporary_files(
        self,
        *,
        older_than: datetime,
        preserve_keys: Collection[str] = (),
    ) -> int: ...

    def list_storage_keys(self) -> set[str]: ...

    def list_storage_keys_older_than(self, *, older_than: datetime) -> set[str]: ...
