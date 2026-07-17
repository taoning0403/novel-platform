import io
import os
import stat
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from novel_platform.application.library.storage import (
    StorageIntegrityError,
    StorageLimitExceeded,
)
from novel_platform.infrastructure.storage.local import LocalFileStorage


def test_local_storage_temporary_commit_checksum_and_restore(tmp_path: Path) -> None:
    storage = LocalFileStorage(tmp_path / "library")
    assert storage.temporary_directory == storage.root / "tmp"
    temporary = storage.write_temporary(io.BytesIO(b"safe novel content"), max_bytes=100)
    assert len(temporary.key) == 64
    assert set(temporary.key) <= set("0123456789abcdef")
    assert temporary.size_bytes == 18
    assert temporary.sha256 == storage.calculate_temporary_checksum(temporary.key)

    storage_key = storage.commit_temporary(temporary.key)
    assert len(storage_key) == 64
    assert set(storage_key) <= set("0123456789abcdef")
    assert storage.exists(storage_key)
    permanent_path = storage.root / "files" / storage_key[:2] / storage_key[2:4] / storage_key
    assert stat.S_IMODE(permanent_path.stat().st_mode) == 0o600
    assert stat.S_IMODE(permanent_path.parent.stat().st_mode) == 0o700
    assert stat.S_IMODE(permanent_path.parent.parent.stat().st_mode) == 0o700
    assert storage.list_storage_keys() == {storage_key}
    assert storage.calculate_checksum(storage_key) == temporary.sha256
    assert storage.open_file(storage_key).read() == b"safe novel content"
    storage.restore_committed(storage_key, temporary.key)
    assert not storage.exists(storage_key)
    assert storage.temporary_exists(temporary.key)


def test_local_storage_rejects_oversize_and_unsafe_keys(tmp_path: Path) -> None:
    storage = LocalFileStorage(tmp_path / "library")
    with pytest.raises(StorageLimitExceeded):
        storage.write_temporary(io.BytesIO(b"too large"), max_bytes=3)
    assert list((storage.root / "tmp").iterdir()) == []
    with pytest.raises(StorageIntegrityError):
        storage.open_file("../secret")


def test_local_storage_cleanup_only_removes_old_regular_files(tmp_path: Path) -> None:
    storage = LocalFileStorage(tmp_path / "library")
    old = storage.write_temporary_bytes(b"old", max_bytes=10)
    preserved = storage.write_temporary_bytes(b"preserved", max_bytes=10)
    current = storage.write_temporary_bytes(b"current", max_bytes=10)
    old_path = storage.temporary_path(old.key)
    preserved_path = storage.temporary_path(preserved.key)
    old_timestamp = (datetime.now(UTC) - timedelta(days=2)).timestamp()
    old_path.touch()
    preserved_path.touch()
    os.utime(old_path, (old_timestamp, old_timestamp))
    os.utime(preserved_path, (old_timestamp, old_timestamp))
    removed = storage.cleanup_temporary_files(
        older_than=datetime.now(UTC) - timedelta(days=1),
        preserve_keys={preserved.key},
    )
    assert removed == 1
    assert not storage.temporary_exists(old.key)
    assert storage.temporary_exists(preserved.key)
    assert storage.temporary_exists(current.key)


def test_local_storage_only_lists_old_permanent_objects_for_orphan_deletion(
    tmp_path: Path,
) -> None:
    storage = LocalFileStorage(tmp_path / "library")
    old = storage.commit_temporary(storage.write_temporary_bytes(b"old", max_bytes=10).key)
    current = storage.commit_temporary(storage.write_temporary_bytes(b"current", max_bytes=10).key)
    old_path = storage.root / "files" / old[:2] / old[2:4] / old
    old_timestamp = (datetime.now(UTC) - timedelta(days=2)).timestamp()
    os.utime(old_path, (old_timestamp, old_timestamp))
    old_keys = storage.list_storage_keys_older_than(
        older_than=datetime.now(UTC) - timedelta(days=1)
    )
    assert old_keys == {old}
    assert current in storage.list_storage_keys()


def test_local_storage_rejects_a_symlink_root(tmp_path: Path) -> None:
    real_root = tmp_path / "real"
    real_root.mkdir()
    symlink_root = tmp_path / "linked"
    symlink_root.symlink_to(real_root, target_is_directory=True)
    with pytest.raises(StorageIntegrityError):
        LocalFileStorage(symlink_root)


def test_permanent_key_collision_never_overwrites_an_existing_object(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    storage = LocalFileStorage(tmp_path / "library")
    existing = storage.commit_temporary(
        storage.write_temporary_bytes(b"existing", max_bytes=10).key
    )
    pending = storage.write_temporary_bytes(b"pending", max_bytes=10)
    replacement = "0" * 64 if existing != "0" * 64 else "1" * 64
    candidates = iter((existing, replacement))
    monkeypatch.setattr(
        "novel_platform.infrastructure.storage.local.token_hex",
        lambda _bytes: next(candidates),
    )

    existing_path = storage.root / "files" / existing[:2] / existing[2:4] / existing
    original_exists = Path.exists
    hidden_once = False

    def hide_collision_once(path: Path) -> bool:
        nonlocal hidden_once
        if path == existing_path and not hidden_once:
            hidden_once = True
            return False
        return original_exists(path)

    monkeypatch.setattr(Path, "exists", hide_collision_once)
    committed = storage.commit_temporary(pending.key)

    assert committed == replacement
    assert storage.open_file(existing).read() == b"existing"
    assert storage.open_file(replacement).read() == b"pending"


def test_delete_io_failure_is_exposed_as_a_path_free_storage_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    storage = LocalFileStorage(tmp_path / "library")
    storage_key = storage.commit_temporary(
        storage.write_temporary_bytes(b"retained orphan", max_bytes=100).key
    )
    target = storage.root / "files" / storage_key[:2] / storage_key[2:4] / storage_key
    original_unlink = Path.unlink

    def deny_target(path: Path, missing_ok: bool = False) -> None:
        if path == target:
            raise PermissionError("test-only denied path")
        original_unlink(path, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", deny_target)
    with pytest.raises(StorageIntegrityError) as caught:
        storage.delete_file(storage_key)

    assert str(target) not in str(caught.value)
    assert storage.exists(storage_key)
