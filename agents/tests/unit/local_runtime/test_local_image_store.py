from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4

import pytest

from pantaray_agents.local_runtime import descriptor_access
from pantaray_agents.local_runtime.runtime import local_image_store
from pantaray_agents.local_runtime.runtime.local_image_store import (
    read_local_image_blob,
    write_local_image_blob,
)
from pantaray_agents.local_runtime.storage.migrations import MigrationError


def _storage_path(*, user_id: str) -> str:
    return f"{user_id}/2026-08-25/{uuid4()}.png"


def test_read_local_image_blob_reads_regular_user_image(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifact_root = tmp_path / "artifacts"
    storage_path = _storage_path(user_id="user-a")
    image_path = artifact_root / "generated" / "images" / storage_path
    image_path.parent.mkdir(parents=True)
    image_path.write_bytes(b"user-a-image")
    monkeypatch.setenv("LOCAL_ARTIFACT_ROOT", str(artifact_root))

    image = read_local_image_blob(user_id="user-a", storage_path=storage_path)

    assert image is not None
    assert image.payload == b"user-a-image"
    assert image.image_relative_path == f"generated/images/{storage_path}"


def test_read_local_image_blob_reads_through_a_symlinked_artifact_root_ancestor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifact_root = tmp_path / "real" / "artifacts"
    storage_path = _storage_path(user_id="user-a")
    image_path = artifact_root / "generated" / "images" / storage_path
    image_path.parent.mkdir(parents=True)
    image_path.write_bytes(b"user-a-image")
    (tmp_path / "link").symlink_to(tmp_path / "real", target_is_directory=True)
    monkeypatch.setenv("LOCAL_ARTIFACT_ROOT", str(tmp_path / "link" / "artifacts"))

    image = read_local_image_blob(user_id="user-a", storage_path=storage_path)

    assert image is not None
    assert image.payload == b"user-a-image"


def test_read_local_image_blob_returns_none_for_missing_image(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifact_root = tmp_path / "artifacts"
    artifact_root.mkdir()
    storage_path = _storage_path(user_id="user-a")
    monkeypatch.setenv("LOCAL_ARTIFACT_ROOT", str(artifact_root))

    assert read_local_image_blob(user_id="user-a", storage_path=storage_path) is None


def test_read_local_image_blob_rejects_symlink_to_another_user_image(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifact_root = tmp_path / "artifacts"
    storage_path = _storage_path(user_id="user-a")
    image_path = artifact_root / "generated" / "images" / storage_path
    other_image = (
        artifact_root / "generated" / "images" / _storage_path(user_id="user-b")
    )
    image_path.parent.mkdir(parents=True)
    other_image.parent.mkdir(parents=True)
    other_image.write_bytes(b"user-b-secret")
    image_path.symlink_to(other_image)
    monkeypatch.setenv("LOCAL_ARTIFACT_ROOT", str(artifact_root))

    with pytest.raises(MigrationError, match="path is unsafe"):
        read_local_image_blob(user_id="user-a", storage_path=storage_path)

    assert other_image.read_bytes() == b"user-b-secret"


def test_read_local_image_blob_stays_on_parent_descriptor_after_ancestor_swap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifact_root = tmp_path / "artifacts"
    storage_path = _storage_path(user_id="user-a")
    image_path = artifact_root / "generated" / "images" / storage_path
    image_path.parent.mkdir(parents=True)
    image_path.write_bytes(b"user-a-image")
    other_user = artifact_root / "generated" / "images" / "user-b"
    other_image = other_user / Path(storage_path).relative_to("user-a")
    other_image.parent.mkdir(parents=True)
    other_image.write_bytes(b"user-b-secret")
    user_directory = image_path.parents[1]
    original_user = user_directory.parent / "original-user-a"
    real_open = os.open
    swapped = False

    def racing_open(
        path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        nonlocal swapped
        if path == image_path.name and dir_fd is not None and not swapped:
            swapped = True
            user_directory.rename(original_user)
            user_directory.symlink_to(other_user, target_is_directory=True)
        return real_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(descriptor_access.os, "open", racing_open)
    monkeypatch.setenv("LOCAL_ARTIFACT_ROOT", str(artifact_root))

    image = read_local_image_blob(user_id="user-a", storage_path=storage_path)

    assert swapped is True
    assert image is not None
    assert image.payload == b"user-a-image"


def test_write_local_image_blob_stores_an_image_the_reader_finds_again(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifact_root = tmp_path / "artifacts"
    artifact_root.mkdir()
    monkeypatch.setenv("LOCAL_ARTIFACT_ROOT", str(artifact_root))

    written = write_local_image_blob(
        user_id="user-a", payload=b"drawn-page", mime_type="image/webp"
    )

    assert written.storage_path.startswith("user-a/")
    assert written.storage_path.endswith(".webp")
    read_back = read_local_image_blob(
        user_id="user-a", storage_path=written.storage_path
    )
    assert read_back is not None
    assert read_back.payload == b"drawn-page"
    assert read_back.mime_type == "image/webp"
    assert (artifact_root / written.image_relative_path).read_bytes() == b"drawn-page"


@pytest.mark.parametrize("user_id", ["", "   ", "user-a/../user-b", "user\na"])
def test_write_local_image_blob_writes_nothing_for_an_unusable_user_id(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    user_id: str,
) -> None:
    """A storage_path is what later authorizes a read, so a bad one writes nothing."""

    artifact_root = tmp_path / "artifacts"
    artifact_root.mkdir()
    monkeypatch.setenv("LOCAL_ARTIFACT_ROOT", str(artifact_root))

    with pytest.raises(ValueError):
        write_local_image_blob(
            user_id=user_id, payload=b"drawn-page", mime_type="image/webp"
        )

    assert list(artifact_root.rglob("*.webp")) == []


def test_write_local_image_blob_leaves_no_partial_image_when_the_move_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifact_root = tmp_path / "artifacts"
    artifact_root.mkdir()
    monkeypatch.setenv("LOCAL_ARTIFACT_ROOT", str(artifact_root))

    def failing_replace(source: object, target: object) -> None:
        raise OSError("no space left on device")

    monkeypatch.setattr(local_image_store.os, "replace", failing_replace)

    with pytest.raises(OSError, match="no space left"):
        write_local_image_blob(
            user_id="user-a", payload=b"drawn-page", mime_type="image/webp"
        )

    # Nothing under generated/images, which is the only tree a storage_path can
    # name, and no half-written file left staged either.
    assert [
        path for path in (artifact_root / "generated").rglob("*") if path.is_file()
    ] == []
    assert list((artifact_root / ".tmp" / "generated-images").iterdir()) == []
