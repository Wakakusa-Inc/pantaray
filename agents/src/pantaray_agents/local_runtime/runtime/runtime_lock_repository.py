from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from ..storage.migrations import MigrationError

BUSY_TIMEOUT_PRAGMA_TEMPLATE = "PRAGMA busy_timeout = {timeout_ms};"
FOREIGN_KEYS_ON_PRAGMA = "PRAGMA foreign_keys = ON;"
RuntimeLockResourceStatus = Literal["active", "cleaned", "cleanup_failed", "abandoned"]
_RUNTIME_LOCK_RESOURCE_STATUSES: tuple[RuntimeLockResourceStatus, ...] = (
    "active",
    "cleaned",
    "cleanup_failed",
    "abandoned",
)


@dataclass(frozen=True, slots=True)
class RuntimeLockResource:
    resource_id: str
    lock_path: str
    lock_id: str
    owner_pid: int
    status: RuntimeLockResourceStatus
    created_at: str
    updated_at: str
    cleaned_at: str | None
    cleanup_error: str | None
    cleanup_attempts: int


def _configure_connection(connection: sqlite3.Connection, busy_timeout_ms: int) -> None:
    if busy_timeout_ms <= 0:
        raise MigrationError("LOCAL_DB_BUSY_TIMEOUT_MS must be a positive integer")
    connection.row_factory = sqlite3.Row
    connection.execute(BUSY_TIMEOUT_PRAGMA_TEMPLATE.format(timeout_ms=busy_timeout_ms))
    connection.execute(FOREIGN_KEYS_ON_PRAGMA)


def create_runtime_lock_resource(
    *,
    db_path: Path,
    busy_timeout_ms: int,
    lock_path: Path,
    lock_id: str,
    owner_pid: int,
    created_at: str,
) -> str:
    resource_id = str(uuid.uuid4())
    with sqlite3.connect(db_path) as connection:
        _configure_connection(connection=connection, busy_timeout_ms=busy_timeout_ms)
        with connection:
            connection.execute(
                """
                INSERT INTO runtime_lock_resources(
                    resource_id,
                    lock_path,
                    lock_id,
                    owner_pid,
                    status,
                    created_at,
                    updated_at,
                    cleaned_at,
                    cleanup_error,
                    cleanup_attempts
                ) VALUES (?, ?, ?, ?, 'active', ?, ?, NULL, NULL, 0)
                """,
                (
                    resource_id,
                    str(lock_path),
                    lock_id,
                    owner_pid,
                    created_at,
                    created_at,
                ),
            )
    return resource_id


def mark_runtime_lock_resource_cleaned(
    *,
    db_path: Path,
    busy_timeout_ms: int,
    resource_id: str,
    cleaned_at: str,
) -> None:
    _update_runtime_lock_resource_status(
        db_path=db_path,
        busy_timeout_ms=busy_timeout_ms,
        resource_id=resource_id,
        status="cleaned",
        timestamp=cleaned_at,
        cleanup_error=None,
    )


def mark_runtime_lock_resource_cleanup_failed(
    *,
    db_path: Path,
    busy_timeout_ms: int,
    resource_id: str,
    failed_at: str,
    cleanup_error: str,
) -> None:
    _update_runtime_lock_resource_status(
        db_path=db_path,
        busy_timeout_ms=busy_timeout_ms,
        resource_id=resource_id,
        status="cleanup_failed",
        timestamp=failed_at,
        cleanup_error=cleanup_error,
    )


def mark_runtime_lock_resource_abandoned(
    *,
    db_path: Path,
    busy_timeout_ms: int,
    resource_id: str,
    abandoned_at: str,
    cleanup_error: str,
) -> None:
    _update_runtime_lock_resource_status(
        db_path=db_path,
        busy_timeout_ms=busy_timeout_ms,
        resource_id=resource_id,
        status="abandoned",
        timestamp=abandoned_at,
        cleanup_error=cleanup_error,
    )


def _update_runtime_lock_resource_status(
    *,
    db_path: Path,
    busy_timeout_ms: int,
    resource_id: str,
    status: RuntimeLockResourceStatus,
    timestamp: str,
    cleanup_error: str | None,
) -> None:
    with sqlite3.connect(db_path) as connection:
        _configure_connection(connection=connection, busy_timeout_ms=busy_timeout_ms)
        with connection:
            cursor = connection.execute(
                """
                UPDATE runtime_lock_resources
                SET
                    status = ?,
                    updated_at = ?,
                    cleaned_at = CASE WHEN ? = 'cleaned' THEN ? ELSE cleaned_at END,
                    cleanup_error = ?,
                    cleanup_attempts = CASE
                        WHEN ? IN ('cleanup_failed', 'abandoned') THEN cleanup_attempts + 1
                        ELSE cleanup_attempts
                    END
                WHERE resource_id = ?
                """,
                (
                    status,
                    timestamp,
                    status,
                    timestamp,
                    cleanup_error,
                    status,
                    resource_id,
                ),
            )
        if cursor.rowcount != 1:
            raise MigrationError(
                "runtime lock resource status update failed: expected exactly one row"
            )


def list_recoverable_runtime_lock_resources(
    *,
    db_path: Path,
    busy_timeout_ms: int,
) -> tuple[RuntimeLockResource, ...]:
    with sqlite3.connect(db_path) as connection:
        _configure_connection(connection=connection, busy_timeout_ms=busy_timeout_ms)
        try:
            rows = connection.execute(
                """
                SELECT
                    resource_id,
                    lock_path,
                    lock_id,
                    owner_pid,
                    status,
                    created_at,
                    updated_at,
                    cleaned_at,
                    cleanup_error,
                    cleanup_attempts
                FROM runtime_lock_resources
                WHERE status IN ('active', 'cleanup_failed')
                ORDER BY created_at ASC
                """
            ).fetchall()
        except sqlite3.OperationalError as exc:
            if "no such table: runtime_lock_resources" in str(exc):
                return ()
            raise
    return tuple(
        RuntimeLockResource(
            resource_id=str(row["resource_id"]),
            lock_path=str(row["lock_path"]),
            lock_id=str(row["lock_id"]),
            owner_pid=int(row["owner_pid"]),
            status=_parse_runtime_lock_resource_status(row["status"]),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
            cleaned_at=str(row["cleaned_at"])
            if row["cleaned_at"] is not None
            else None,
            cleanup_error=(
                str(row["cleanup_error"]) if row["cleanup_error"] is not None else None
            ),
            cleanup_attempts=int(row["cleanup_attempts"]),
        )
        for row in rows
    )


def _parse_runtime_lock_resource_status(value: object) -> RuntimeLockResourceStatus:
    status = str(value)
    if status not in _RUNTIME_LOCK_RESOURCE_STATUSES:
        raise MigrationError(f"unsupported runtime lock resource status: {status}")
    return status


def record_runtime_lock_event(
    *,
    db_path: Path,
    busy_timeout_ms: int,
    resource_id: str | None,
    event_type: str,
    message: str,
    created_at: str,
) -> None:
    with sqlite3.connect(db_path) as connection:
        _configure_connection(connection=connection, busy_timeout_ms=busy_timeout_ms)
        with connection:
            connection.execute(
                """
                INSERT INTO runtime_lock_events(
                    event_id,
                    resource_id,
                    event_type,
                    message,
                    created_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (str(uuid.uuid4()), resource_id, event_type, message, created_at),
            )


__all__ = [
    "RuntimeLockResource",
    "create_runtime_lock_resource",
    "list_recoverable_runtime_lock_resources",
    "mark_runtime_lock_resource_abandoned",
    "mark_runtime_lock_resource_cleaned",
    "mark_runtime_lock_resource_cleanup_failed",
    "record_runtime_lock_event",
]
