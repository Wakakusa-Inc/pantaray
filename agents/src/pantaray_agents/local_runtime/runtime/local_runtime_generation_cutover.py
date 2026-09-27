from __future__ import annotations

import os
import shutil
import sqlite3
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from ..artifacts.paths import normalize_artifact_root
from ..storage.migrations import MigrationError
from ..tooling.action_session_temp_paths import LOCAL_RUNTIME_WORKSPACE_DIRNAME
from ..tooling.locks.workspace_lock import workspace_lock_store_path
from ..tooling.models import StoredToolRuntimeResource, ToolRuntimeResourceStatus
from ..tooling.resources.resource_cleanup import cleanup_runtime_resource
from .process_lock import RuntimeProcessLock, runtime_process_lock_path

# Stores older than the logged-out owner generation are replaced on startup.
LOCAL_RUNTIME_RESET_VERSION = 112
_DATABASE_SIDECAR_SUFFIXES = ("-wal", "-shm", "-journal")
_PRE_MEMORY_CATALOG_BACKUP_SUFFIX = ".bak"


def reset_legacy_local_runtime_generation(
    *,
    db_path: Path,
    busy_timeout_ms: int,
    artifact_root: Path,
    runtime_lock: RuntimeProcessLock,
) -> bool:
    if busy_timeout_ms <= 0:
        raise MigrationError("LOCAL_DB_BUSY_TIMEOUT_MS must be a positive integer")
    marker = _inspect_local_runtime_store(db_path)
    if marker.schema_version >= LOCAL_RUNTIME_RESET_VERSION:
        return False
    targets = _validate_reset_targets(
        db_path=db_path,
        artifact_root=artifact_root,
        runtime_lock=runtime_lock,
    )
    if marker.has_tool_runtime_resources:
        _cleanup_process_group_resources(
            db_path=db_path,
            busy_timeout_ms=busy_timeout_ms,
        )
    elif marker.schema_version >= 10:
        raise MigrationError(
            "Pre-v89 local runtime is missing its tool resource authority"
        )
    try:
        for target in targets.external_trees:
            _remove_path_without_following_symlinks(target)
        for backup in targets.pre_memory_catalog_backups:
            _remove_path_without_following_symlinks(backup)
        _fsync_directory(targets.db_path.parent)
        _unlink_owned_file(targets.db_path)
        for sidecar in targets.database_sidecars:
            _unlink_owned_file(sidecar)
        _fsync_directory(targets.db_path.parent)
    except OSError as exc:
        raise MigrationError("Local runtime generation reset failed") from exc
    return True


@dataclass(frozen=True, slots=True)
class _ResetTargets:
    db_path: Path
    external_trees: tuple[Path, ...]
    pre_memory_catalog_backups: tuple[Path, ...]
    database_sidecars: tuple[Path, ...]


@dataclass(frozen=True, slots=True)
class _StoreMarker:
    schema_version: int
    has_tool_runtime_resources: bool


def _validate_reset_targets(
    *,
    db_path: Path,
    artifact_root: Path,
    runtime_lock: RuntimeProcessLock,
) -> _ResetTargets:
    if not db_path.is_absolute():
        raise MigrationError("Local runtime database path must be absolute")
    if artifact_root.name == "..":
        raise MigrationError("LOCAL_ARTIFACT_ROOT must not end with '..'")
    canonical_db_path = db_path.resolve()
    db_parent = canonical_db_path.parent
    normalized_artifact_root = (
        normalize_artifact_root(artifact_root.parent) / artifact_root.name
    )
    if (
        db_parent == Path(canonical_db_path.anchor)
        or normalized_artifact_root.parent.resolve() != db_parent
    ):
        raise MigrationError(
            "LOCAL_ARTIFACT_ROOT must be a direct child of the local database directory"
        )
    canonical_artifact_root = db_parent / normalized_artifact_root.name
    process_lock_path = runtime_process_lock_path(db_path=canonical_db_path)
    if (
        runtime_lock.owner_pid != os.getpid()
        or runtime_lock.lock_path != process_lock_path
        or runtime_lock.file_descriptor < 0
    ):
        raise MigrationError("Local runtime generation reset requires the process lock")

    workspace_root = db_parent / LOCAL_RUNTIME_WORKSPACE_DIRNAME
    workspace_locks = workspace_lock_store_path(db_path=canonical_db_path)
    external_trees = (canonical_artifact_root, workspace_root, workspace_locks)
    protected_paths = {canonical_db_path, process_lock_path}
    if len(set(external_trees)) != len(external_trees) or any(
        target in protected_paths for target in external_trees
    ):
        raise MigrationError("Local runtime reset paths overlap")

    backups = (
        tuple(
            path
            for path in sorted(
                db_parent.iterdir(), key=lambda candidate: candidate.name
            )
            if _is_pre_memory_catalog_backup(
                path=path,
                db_path=canonical_db_path,
                artifact_root=canonical_artifact_root,
            )
        )
        if db_parent.exists()
        else ()
    )
    sidecars = tuple(
        Path(f"{canonical_db_path}{suffix}") for suffix in _DATABASE_SIDECAR_SUFFIXES
    )
    return _ResetTargets(
        db_path=canonical_db_path,
        external_trees=external_trees,
        pre_memory_catalog_backups=backups,
        database_sidecars=sidecars,
    )


def _is_pre_memory_catalog_backup(
    *, path: Path, db_path: Path, artifact_root: Path
) -> bool:
    return path.name.endswith(
        _PRE_MEMORY_CATALOG_BACKUP_SUFFIX
    ) and path.name.startswith(
        (
            f"{db_path.name}.pre-memory-catalog-",
            f"{artifact_root.name}.pre-memory-catalog-",
        )
    )


def _inspect_local_runtime_store(db_path: Path) -> _StoreMarker:
    try:
        db_path.lstat()
    except FileNotFoundError:
        return _StoreMarker(schema_version=0, has_tool_runtime_resources=False)
    try:
        with sqlite3.connect(f"{db_path.as_uri()}?mode=ro", uri=True) as connection:
            tables = {
                str(row[0])
                for row in connection.execute(
                    "SELECT name FROM sqlite_schema WHERE type = 'table'"
                )
            }
            if "schema_versions" not in tables:
                schema_version = 0
            else:
                row = connection.execute(
                    """
                    SELECT current_version
                    FROM schema_versions
                    WHERE component = 'local_runtime'
                    """
                ).fetchone()
                if row is None:
                    schema_version = 0
                elif not isinstance(row[0], int) or row[0] < 0:
                    raise MigrationError(
                        "Local runtime schema version marker is invalid"
                    )
                else:
                    schema_version = int(row[0])
    except sqlite3.DatabaseError as exc:
        raise MigrationError("Local runtime schema version could not be read") from exc
    return _StoreMarker(
        schema_version=schema_version,
        has_tool_runtime_resources="tool_runtime_resources" in tables,
    )


def _cleanup_process_group_resources(*, db_path: Path, busy_timeout_ms: int) -> None:
    try:
        with sqlite3.connect(f"{db_path.as_uri()}?mode=ro", uri=True) as connection:
            connection.row_factory = sqlite3.Row
            connection.execute(f"PRAGMA busy_timeout = {busy_timeout_ms}")
            rows = connection.execute(
                """
                SELECT resource_id, execution_session_id, tool_invocation_id,
                       action_id, status, pid, pgid, process_start_signature,
                       resource_path, created_at, updated_at, cleaned_at,
                       cleanup_error, cleanup_attempts
                FROM tool_runtime_resources
                WHERE resource_kind = 'process_group'
                  AND status IN ('active', 'cleanup_failed', 'abandoned')
                ORDER BY resource_id
                """
            ).fetchall()
        resources = tuple(_build_process_group_resource(row) for row in rows)
    except (sqlite3.DatabaseError, TypeError, ValueError) as exc:
        raise MigrationError(
            "Process-group cleanup authority could not be loaded"
        ) from exc

    for resource in resources:
        try:
            cleanup_runtime_resource(resource)
        except (OSError, RuntimeError, ValueError) as exc:
            raise MigrationError(
                f"Process-group cleanup failed for resource {resource.resource_id}"
            ) from exc


def _build_process_group_resource(row: sqlite3.Row) -> StoredToolRuntimeResource:
    return StoredToolRuntimeResource(
        resource_id=str(row["resource_id"]),
        execution_session_id=str(row["execution_session_id"]),
        tool_invocation_id=_optional_text(row["tool_invocation_id"]),
        action_id=_optional_text(row["action_id"]),
        resource_kind="process_group",
        status=cast(ToolRuntimeResourceStatus, str(row["status"])),
        pid=_optional_integer(row["pid"]),
        pgid=_optional_integer(row["pgid"]),
        process_start_signature=_optional_text(row["process_start_signature"]),
        resource_path=_optional_text(row["resource_path"]),
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
        cleaned_at=_optional_text(row["cleaned_at"]),
        cleanup_error=_optional_text(row["cleanup_error"]),
        cleanup_attempts=int(row["cleanup_attempts"]),
    )


def _optional_text(value: object) -> str | None:
    return str(value) if value is not None else None


def _optional_integer(value: object) -> int | None:
    if value is not None and not isinstance(value, int):
        raise ValueError("process-group integer authority is invalid")
    return value


def _remove_path_without_following_symlinks(path: Path) -> None:
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError:
        return
    if stat.S_ISDIR(mode):
        shutil.rmtree(path)
        return
    path.unlink()


def _unlink_owned_file(path: Path) -> None:
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError:
        return
    if stat.S_ISDIR(mode):
        raise IsADirectoryError(path)
    path.unlink()


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
