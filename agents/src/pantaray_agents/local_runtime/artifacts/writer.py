from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path

from ..storage.migrations import MigrationError
from .models import ArtifactKind, ManagedArtifactWriteResult
from .paths import build_managed_artifact_location, normalize_artifact_root


def _compute_sha256(file_path: Path) -> str:
    digest = hashlib.sha256()
    with file_path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _fsync_directory(directory_path: Path) -> None:
    dir_fd: int | None = None
    try:
        dir_fd = os.open(str(directory_path), os.O_RDONLY)
        os.fsync(dir_fd)
    except Exception as exc:
        raise MigrationError(
            f"failed to fsync managed artifact directory: {directory_path}"
        ) from exc
    finally:
        if dir_fd is not None:
            os.close(dir_fd)


def write_managed_file_artifact(
    *,
    root_path: Path,
    kind: ArtifactKind,
    artifact_id: str,
    file_name: str,
    payload: bytes,
) -> ManagedArtifactWriteResult:
    normalized_root = normalize_artifact_root(root_path)
    location = build_managed_artifact_location(
        root_path=normalized_root,
        kind=kind,
        artifact_id=artifact_id,
        file_name=file_name,
    )
    location.absolute_path.parent.mkdir(parents=True, exist_ok=True)

    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=str(location.absolute_path.parent),
            prefix=".tmp-",
            delete=False,
        ) as handle:
            temp_path = Path(handle.name)
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, location.absolute_path)
        _fsync_directory(location.absolute_path.parent)
    except Exception as exc:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
        raise MigrationError(
            f"failed to atomically write managed artifact: {location.relative_path}"
        ) from exc

    checksum_sha256 = _compute_sha256(location.absolute_path)
    file_size_bytes = location.absolute_path.stat().st_size
    if file_size_bytes != len(payload):
        raise MigrationError(
            f"managed artifact size mismatch after write: {location.relative_path}"
        )

    return ManagedArtifactWriteResult(
        kind=kind,
        relative_path=location.relative_path,
        absolute_path=location.absolute_path,
        checksum_sha256=checksum_sha256,
        file_size_bytes=file_size_bytes,
    )
