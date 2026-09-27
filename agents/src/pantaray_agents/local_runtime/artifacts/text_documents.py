from __future__ import annotations

import hashlib
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from ..storage.migrations import MigrationError
from .models import ArtifactKind
from .paths import (
    normalize_artifact_root,
    resolve_artifact_path,
    validate_relative_artifact_path,
)

LOCAL_ARTIFACT_ROOT_ENV = "LOCAL_ARTIFACT_ROOT"
TEXT_CONTENT_ENCODING = "utf-8"
TEXT_CONTENT_TYPE = "text/plain; charset=utf-8"


@dataclass(frozen=True, slots=True)
class LocalTextArtifactDocument:
    kind: ArtifactKind
    user_id: str
    relative_path: str
    absolute_path: Path
    plaintext: str
    sha256: str
    byte_size: int


def _require_non_empty_env(name: str) -> str:
    value = os.getenv(name)
    if value is None or not value.strip():
        raise MigrationError(f"Missing required environment variable: {name}")
    return value


def _read_local_artifact_root() -> Path:
    return normalize_artifact_root(
        Path(_require_non_empty_env(LOCAL_ARTIFACT_ROOT_ENV))
    )


def resolve_local_text_artifact_relative_path(*, template: str, user_id: str) -> str:
    """local text artifact の相対パスを storage path template から決定する。

    template は ``config_tunables.toml`` の読み込み時に ``{user_id}`` を含むことが
    検証済みであるため、ここでは再検証しない。
    """
    if not user_id:
        raise ValueError("user_id must not be empty")
    return validate_relative_artifact_path(template.format(user_id=user_id))


def _compute_sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _fsync_directory(directory_path: Path) -> None:
    dir_fd: int | None = None
    try:
        dir_fd = os.open(str(directory_path), os.O_RDONLY)
        os.fsync(dir_fd)
    except OSError as exc:
        raise MigrationError(
            f"failed to fsync artifact directory: {directory_path}"
        ) from exc
    finally:
        if dir_fd is not None:
            os.close(dir_fd)


def _write_bytes_atomic(*, absolute_path: Path, payload: bytes) -> int:
    absolute_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=str(absolute_path.parent),
            prefix=".tmp-",
            delete=False,
        ) as handle:
            temp_path = Path(handle.name)
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, absolute_path)
        _fsync_directory(absolute_path.parent)
    except OSError as exc:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
        raise MigrationError(
            f"failed to atomically write local artifact: {absolute_path}"
        ) from exc
    return absolute_path.stat().st_size


def _read_document(
    *, kind: ArtifactKind, user_id: str, relative_path: str, absolute_path: Path
) -> LocalTextArtifactDocument:
    payload = absolute_path.read_bytes()
    plaintext = payload.decode(TEXT_CONTENT_ENCODING, errors="strict")
    plaintext_bytes = plaintext.encode(TEXT_CONTENT_ENCODING)
    return LocalTextArtifactDocument(
        kind=kind,
        user_id=user_id,
        relative_path=relative_path,
        absolute_path=absolute_path,
        plaintext=plaintext,
        sha256=_compute_sha256(plaintext_bytes),
        byte_size=len(plaintext_bytes),
    )


def ensure_local_text_artifact(
    *,
    kind: ArtifactKind,
    template: str,
    user_id: str,
    initial_plaintext: str = "",
) -> LocalTextArtifactDocument:
    root_path = _read_local_artifact_root()
    relative_path = resolve_local_text_artifact_relative_path(
        template=template, user_id=user_id
    )
    absolute_path = resolve_artifact_path(
        root_path=root_path, relative_path=relative_path
    )
    if not absolute_path.exists():
        payload = initial_plaintext.encode(TEXT_CONTENT_ENCODING)
        _write_bytes_atomic(absolute_path=absolute_path, payload=payload)
    return _read_document(
        kind=kind,
        user_id=user_id,
        relative_path=relative_path,
        absolute_path=absolute_path,
    )


def write_local_text_artifact(
    *,
    kind: ArtifactKind,
    user_id: str,
    relative_path: str,
    plaintext: str,
) -> LocalTextArtifactDocument:
    root_path = _read_local_artifact_root()
    normalized_relative_path = validate_relative_artifact_path(relative_path)
    absolute_path = resolve_artifact_path(
        root_path=root_path,
        relative_path=normalized_relative_path,
    )
    payload = plaintext.encode(TEXT_CONTENT_ENCODING)
    _write_bytes_atomic(absolute_path=absolute_path, payload=payload)
    plaintext_bytes = plaintext.encode(TEXT_CONTENT_ENCODING)
    return LocalTextArtifactDocument(
        kind=kind,
        user_id=user_id,
        relative_path=normalized_relative_path,
        absolute_path=absolute_path,
        plaintext=plaintext,
        sha256=_compute_sha256(plaintext_bytes),
        byte_size=len(plaintext_bytes),
    )


__all__ = [
    "LOCAL_ARTIFACT_ROOT_ENV",
    "LocalTextArtifactDocument",
    "resolve_local_text_artifact_relative_path",
    "TEXT_CONTENT_TYPE",
    "ensure_local_text_artifact",
    "write_local_text_artifact",
]
