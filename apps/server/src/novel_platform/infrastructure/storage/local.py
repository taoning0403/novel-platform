import hashlib
import io
import os
import re
import stat
from collections.abc import Collection
from datetime import datetime
from pathlib import Path
from secrets import token_hex
from typing import BinaryIO

from novel_platform.application.library.storage import (
    StorageIntegrityError,
    StorageLimitExceeded,
    StorageObjectNotFound,
    TemporaryFile,
)

_KEY_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_CHUNK_SIZE = 1024 * 1024


class LocalFileStorage:
    """Local filesystem backend whose callers never construct storage paths."""

    def __init__(self, root: Path) -> None:
        expanded_root = root.expanduser()
        if expanded_root.is_symlink():
            raise StorageIntegrityError("storage root cannot be a symbolic link")
        self._root = expanded_root.resolve()
        if self._root == Path(self._root.anchor):
            raise StorageIntegrityError("storage root cannot be a filesystem root")
        self._temporary_root = self._root / "tmp"
        self._files_root = self._root / "files"
        self.initialize()

    @property
    def root(self) -> Path:
        return self._root

    @property
    def temporary_directory(self) -> Path:
        return self._temporary_root

    def initialize(self) -> None:
        try:
            for directory in (self._root, self._temporary_root, self._files_root):
                directory.mkdir(parents=True, exist_ok=True, mode=0o700)
                if directory.is_symlink() or not directory.is_dir():
                    raise StorageIntegrityError("storage directory is not a regular directory")
                directory.chmod(0o700)
        except OSError as exc:
            raise StorageIntegrityError("could not initialize storage directories") from exc
        probe = self._temporary_root / f".{token_hex(16)}.probe"
        try:
            probe.write_bytes(b"")
            probe.chmod(0o600)
        except OSError as exc:
            try:
                probe.unlink(missing_ok=True)
            except OSError:
                pass
            raise StorageIntegrityError("storage root is not writable") from exc
        try:
            probe.unlink(missing_ok=True)
        except OSError as exc:
            raise StorageIntegrityError("storage root probe could not be removed") from exc

    def write_temporary(self, stream: BinaryIO, *, max_bytes: int) -> TemporaryFile:
        key = self.allocate_temporary()
        destination = self.temporary_path(key)
        digest = hashlib.sha256()
        total = 0
        try:
            with destination.open("wb") as output:
                while chunk := stream.read(_CHUNK_SIZE):
                    total += len(chunk)
                    if total > max_bytes:
                        raise StorageLimitExceeded("upload exceeds configured size limit")
                    digest.update(chunk)
                    output.write(chunk)
                output.flush()
                os.fsync(output.fileno())
            destination.chmod(0o600)
        except Exception as exc:
            try:
                destination.unlink(missing_ok=True)
            except OSError:
                pass
            if isinstance(exc, OSError):
                raise StorageIntegrityError("could not write temporary object") from exc
            raise
        return TemporaryFile(key=key, size_bytes=total, sha256=digest.hexdigest())

    def write_temporary_bytes(self, content: bytes, *, max_bytes: int) -> TemporaryFile:
        return self.write_temporary(io.BytesIO(content), max_bytes=max_bytes)

    def allocate_temporary(self) -> str:
        for _ in range(10):
            key = token_hex(32)
            path = self._temporary_root / key
            try:
                descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            except FileExistsError:
                continue
            except OSError as exc:
                raise StorageIntegrityError("could not allocate a temporary object") from exc
            os.close(descriptor)
            return key
        raise StorageIntegrityError("could not allocate a temporary object")

    def temporary_path(self, key: str) -> Path:
        self._validate_key(key)
        return self._temporary_root / key

    def commit_temporary(self, key: str) -> str:
        source = self.temporary_path(key)
        self._require_regular_file(source)
        for _ in range(10):
            storage_key = token_hex(32)
            destination = self._file_path(storage_key)
            try:
                destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                destination.parent.parent.chmod(0o700)
                destination.parent.chmod(0o700)
            except OSError as exc:
                raise StorageIntegrityError("could not prepare permanent storage") from exc
            if destination.exists():
                continue
            try:
                os.link(source, destination, follow_symlinks=False)
            except FileExistsError:
                continue
            except OSError as exc:
                raise StorageIntegrityError("could not commit temporary object") from exc
            try:
                destination.chmod(0o600)
                os.utime(destination, None)
                source.unlink()
                return storage_key
            except OSError as exc:
                try:
                    destination.unlink(missing_ok=True)
                except OSError:
                    pass
                raise StorageIntegrityError("could not commit temporary object") from exc
        raise StorageIntegrityError("could not allocate a permanent object")

    def restore_committed(self, storage_key: str, temporary_key: str) -> None:
        source = self._file_path(storage_key)
        destination = self.temporary_path(temporary_key)
        self._require_regular_file(source)
        if destination.exists():
            raise StorageIntegrityError("temporary restore destination already exists")
        try:
            os.link(source, destination, follow_symlinks=False)
        except FileExistsError as exc:
            raise StorageIntegrityError("temporary restore destination already exists") from exc
        except OSError as exc:
            raise StorageIntegrityError("could not restore committed object") from exc
        try:
            destination.chmod(0o600)
            source.unlink()
        except OSError as exc:
            try:
                destination.unlink(missing_ok=True)
            except OSError:
                pass
            raise StorageIntegrityError("could not restore committed object") from exc

    def open_file(self, storage_key: str) -> BinaryIO:
        path = self._file_path(storage_key)
        self._require_regular_file(path)
        try:
            return path.open("rb")
        except OSError as exc:
            raise StorageIntegrityError("could not open stored object") from exc

    def open_temporary(self, key: str) -> BinaryIO:
        path = self.temporary_path(key)
        self._require_regular_file(path)
        try:
            return path.open("rb")
        except OSError as exc:
            raise StorageIntegrityError("could not open temporary object") from exc

    def delete_file(self, storage_key: str) -> None:
        path = self._file_path(storage_key)
        self._delete_regular_file(path)
        for parent in (path.parent, path.parent.parent):
            try:
                parent.rmdir()
            except OSError:
                break

    def delete_temporary(self, key: str) -> None:
        self._delete_regular_file(self.temporary_path(key))

    def exists(self, storage_key: str) -> bool:
        return self._is_regular_file(self._file_path(storage_key))

    def temporary_exists(self, key: str) -> bool:
        return self._is_regular_file(self.temporary_path(key))

    def calculate_checksum(self, storage_key: str) -> str:
        return self._checksum(self._file_path(storage_key))

    def calculate_temporary_checksum(self, key: str) -> str:
        return self._checksum(self.temporary_path(key))

    def cleanup_temporary_files(
        self,
        *,
        older_than: datetime,
        preserve_keys: Collection[str] = (),
    ) -> int:
        removed = 0
        threshold = older_than.timestamp()
        try:
            for path in self._temporary_root.iterdir():
                try:
                    metadata = path.lstat()
                except FileNotFoundError:
                    continue
                if (
                    stat.S_ISREG(metadata.st_mode)
                    and metadata.st_mtime < threshold
                    and path.name not in preserve_keys
                ):
                    try:
                        path.unlink()
                    except FileNotFoundError:
                        continue
                    removed += 1
        except StorageIntegrityError:
            raise
        except OSError as exc:
            raise StorageIntegrityError("could not clean temporary storage") from exc
        return removed

    def list_storage_keys(self) -> set[str]:
        return self._list_storage_keys()

    def list_storage_keys_older_than(self, *, older_than: datetime) -> set[str]:
        return self._list_storage_keys(older_than=older_than)

    def _list_storage_keys(self, *, older_than: datetime | None = None) -> set[str]:
        keys: set[str] = set()
        threshold = older_than.timestamp() if older_than is not None else None
        try:
            for path in self._files_root.rglob("*"):
                try:
                    metadata = path.lstat()
                except FileNotFoundError:
                    continue
                if not stat.S_ISREG(metadata.st_mode):
                    continue
                if (
                    _KEY_PATTERN.fullmatch(path.name)
                    and path == self._file_path(path.name)
                    and (threshold is None or metadata.st_mtime < threshold)
                ):
                    keys.add(path.name)
        except StorageIntegrityError:
            raise
        except OSError as exc:
            raise StorageIntegrityError("could not inspect permanent storage") from exc
        return keys

    def _file_path(self, key: str) -> Path:
        self._validate_key(key)
        return self._files_root / key[:2] / key[2:4] / key

    @staticmethod
    def _validate_key(key: str) -> None:
        if not _KEY_PATTERN.fullmatch(key):
            raise StorageIntegrityError("invalid storage key")

    @staticmethod
    def _is_regular_file(path: Path) -> bool:
        try:
            metadata = path.lstat()
        except FileNotFoundError:
            return False
        except OSError as exc:
            raise StorageIntegrityError("could not inspect stored object") from exc
        return stat.S_ISREG(metadata.st_mode)

    def _require_regular_file(self, path: Path) -> None:
        if not self._is_regular_file(path):
            raise StorageObjectNotFound("stored object does not exist")

    def _delete_regular_file(self, path: Path) -> None:
        try:
            metadata = path.lstat()
        except FileNotFoundError:
            return
        except OSError as exc:
            raise StorageIntegrityError("could not inspect stored object") from exc
        if not stat.S_ISREG(metadata.st_mode):
            raise StorageIntegrityError("stored object is not a regular file")
        try:
            path.unlink()
        except OSError as exc:
            raise StorageIntegrityError("could not delete stored object") from exc

    def _checksum(self, path: Path) -> str:
        self._require_regular_file(path)
        digest = hashlib.sha256()
        try:
            with path.open("rb") as source:
                while chunk := source.read(_CHUNK_SIZE):
                    digest.update(chunk)
        except OSError as exc:
            raise StorageIntegrityError("could not read stored object") from exc
        return digest.hexdigest()
