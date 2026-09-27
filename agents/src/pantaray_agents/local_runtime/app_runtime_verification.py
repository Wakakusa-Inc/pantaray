from __future__ import annotations

import hashlib
import json
import os
import platform
import sys
from dataclasses import dataclass
from pathlib import Path

from .storage.migrations import MigrationError

LOCAL_APP_RUNTIME_MANIFEST_PATH_ENV = "LOCAL_APP_RUNTIME_MANIFEST_PATH"
HASH_READ_CHUNK_BYTES = 1024 * 1024


@dataclass(frozen=True, slots=True)
class AppRuntimeManifest:
    python_path: Path
    python_version: str
    python_sha256: str


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(HASH_READ_CHUNK_BYTES), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_app_runtime_manifest(*, manifest_path: Path) -> AppRuntimeManifest:
    if not manifest_path.is_file():
        raise MigrationError(
            f"app runtime manifest path must reference an existing file: {manifest_path}"
        )
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise MigrationError("app runtime manifest must be valid JSON") from exc
    if not isinstance(payload, dict):
        raise MigrationError("app runtime manifest must decode to an object")
    python_path = payload.get("python_path")
    python_version = payload.get("python_version")
    python_sha256 = payload.get("python_sha256")
    if not all(
        isinstance(value, str) and value.strip()
        for value in (python_path, python_version, python_sha256)
    ):
        raise MigrationError(
            "app runtime manifest requires non-empty python_path, python_version, and python_sha256"
        )
    return AppRuntimeManifest(
        python_path=Path(python_path).resolve(),
        python_version=python_version,
        python_sha256=python_sha256,
    )


def load_app_runtime_manifest_from_env() -> AppRuntimeManifest:
    raw_manifest_path = os.getenv(LOCAL_APP_RUNTIME_MANIFEST_PATH_ENV)
    if raw_manifest_path is None or not raw_manifest_path.strip():
        raise MigrationError(
            "Missing required environment variable: "
            f"{LOCAL_APP_RUNTIME_MANIFEST_PATH_ENV}"
        )
    return load_app_runtime_manifest(manifest_path=Path(raw_manifest_path))


def verify_app_runtime_python(*, manifest: AppRuntimeManifest) -> Path:
    actual_python = Path(sys.executable).resolve()
    if actual_python != manifest.python_path:
        raise MigrationError(
            "app runtime python path does not match manifest: "
            f"expected {manifest.python_path}, got {actual_python}"
        )
    actual_version = platform.python_version()
    if actual_version != manifest.python_version:
        raise MigrationError(
            "app runtime python version does not match manifest: "
            f"expected {manifest.python_version}, got {actual_version}"
        )
    actual_hash = _hash_file(actual_python)
    if actual_hash != manifest.python_sha256:
        raise MigrationError(
            "app runtime python hash does not match manifest: "
            f"expected {manifest.python_sha256}, got {actual_hash}"
        )
    return actual_python


def load_and_verify_app_runtime_python_from_env() -> Path:
    manifest = load_app_runtime_manifest_from_env()
    return verify_app_runtime_python(manifest=manifest)
