from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

from .errors import MemoryCutoverError


def parse_cutover_inventory(raw: str) -> dict[str, object]:
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise MemoryCutoverError("Memory Catalog cutover inventory is invalid") from exc
    if not isinstance(parsed, dict) or not all(isinstance(key, str) for key in parsed):
        raise MemoryCutoverError("Memory Catalog cutover inventory is invalid")
    return dict(parsed)


def finalize_completed_cutover(
    *, db_path: Path, artifact_root: Path, inventory: dict[str, object]
) -> None:
    try:
        staging_root = artifact_root / "memory_catalog" / "cutover_staging"
        if staging_root.exists():
            shutil.rmtree(staging_root)
            _fsync_directory(staging_root.parent)
        legacy_root = artifact_root / "memory"
        if legacy_root.exists():
            shutil.rmtree(legacy_root)
            _fsync_directory(legacy_root.parent)
        _remove_database_backup(db_path=db_path, value=inventory.get("backup_database"))
        _remove_artifact_backup(
            artifact_root=artifact_root,
            value=inventory.get("backup_artifacts"),
        )
    except OSError as exc:
        raise MemoryCutoverError(
            "completed Memory Catalog cutover cleanup is incomplete"
        ) from exc


def _remove_database_backup(*, db_path: Path, value: object) -> None:
    if value is None:
        return
    backup = _validated_backup_path(
        value=value,
        parent=db_path.parent,
        name_prefix=f"{db_path.name}.pre-memory-catalog-",
    )
    backup.unlink(missing_ok=True)
    _fsync_directory(backup.parent)


def _remove_artifact_backup(*, artifact_root: Path, value: object) -> None:
    if value is None:
        return
    backup = _validated_backup_path(
        value=value,
        parent=artifact_root.parent,
        name_prefix=f"{artifact_root.name}.pre-memory-catalog-",
    )
    if backup.exists():
        shutil.rmtree(backup)
        _fsync_directory(backup.parent)


def _validated_backup_path(*, value: object, parent: Path, name_prefix: str) -> Path:
    if not isinstance(value, str):
        raise MemoryCutoverError("Memory Catalog cutover backup path is invalid")
    backup = Path(value)
    if (
        backup.parent.resolve() != parent.resolve()
        or not backup.name.startswith(name_prefix)
        or not backup.name.endswith(".bak")
    ):
        raise MemoryCutoverError("Memory Catalog cutover backup path is invalid")
    return backup


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
