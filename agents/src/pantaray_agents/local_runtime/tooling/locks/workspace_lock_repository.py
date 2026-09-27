from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from ...storage.migrations import MigrationError
from ..models import (
    StoredToolRuntimeResource,
    ToolInvocationStatus,
    ToolRuntimeResourceStatus,
)
from .workspace_lock import workspace_root_lock_path

BUSY_TIMEOUT_PRAGMA_TEMPLATE = "PRAGMA busy_timeout = {timeout_ms};"
FOREIGN_KEYS_ON_PRAGMA = "PRAGMA foreign_keys = ON;"


@dataclass(frozen=True, slots=True)
class StoredLockResource:
    resource: StoredToolRuntimeResource
    lock_key: str
    tool_invocation_status: ToolInvocationStatus | None


def _configure_connection(connection: sqlite3.Connection, busy_timeout_ms: int) -> None:
    if busy_timeout_ms <= 0:
        raise MigrationError("LOCAL_DB_BUSY_TIMEOUT_MS must be a positive integer")
    connection.row_factory = sqlite3.Row
    connection.execute(BUSY_TIMEOUT_PRAGMA_TEMPLATE.format(timeout_ms=busy_timeout_ms))
    connection.execute(FOREIGN_KEYS_ON_PRAGMA)


def list_recoverable_workspace_lock_resources(
    *,
    db_path: Path,
    busy_timeout_ms: int,
    lock_key: str,
) -> tuple[StoredLockResource, ...]:
    lock_path = workspace_root_lock_path(db_path=db_path, lock_key=lock_key)
    with sqlite3.connect(db_path) as connection:
        _configure_connection(connection=connection, busy_timeout_ms=busy_timeout_ms)
        rows = connection.execute(
            """
            SELECT
                resource.resource_id,
                resource.execution_session_id,
                resource.tool_invocation_id,
                resource.action_id,
                resource.resource_kind,
                resource.status,
                resource.pid,
                resource.pgid,
                resource.process_start_signature,
                resource.resource_path,
                resource.lock_id,
                resource.created_at,
                resource.updated_at,
                resource.cleaned_at,
                resource.cleanup_error,
                resource.cleanup_attempts,
                invocation.status AS tool_invocation_status
            FROM tool_runtime_resources AS resource
            LEFT JOIN tool_invocations AS invocation
                ON invocation.invocation_id = resource.tool_invocation_id
            WHERE
                resource.resource_kind = 'lock'
                AND resource.status IN ('active', 'cleanup_failed')
                AND resource.resource_path = ?
            ORDER BY resource.created_at ASC
            """,
            (str(lock_path),),
        ).fetchall()
    return tuple(
        StoredLockResource(
            resource=StoredToolRuntimeResource(
                resource_id=str(row["resource_id"]),
                execution_session_id=str(row["execution_session_id"]),
                tool_invocation_id=(
                    str(row["tool_invocation_id"])
                    if row["tool_invocation_id"] is not None
                    else None
                ),
                action_id=str(row["action_id"])
                if row["action_id"] is not None
                else None,
                resource_kind="lock",
                status=cast(ToolRuntimeResourceStatus, str(row["status"])),
                pid=int(row["pid"]) if row["pid"] is not None else None,
                pgid=int(row["pgid"]) if row["pgid"] is not None else None,
                process_start_signature=(
                    str(row["process_start_signature"])
                    if row["process_start_signature"] is not None
                    else None
                ),
                resource_path=(
                    str(row["resource_path"])
                    if row["resource_path"] is not None
                    else None
                ),
                created_at=str(row["created_at"]),
                updated_at=str(row["updated_at"]),
                cleaned_at=str(row["cleaned_at"])
                if row["cleaned_at"] is not None
                else None,
                cleanup_error=(
                    str(row["cleanup_error"])
                    if row["cleanup_error"] is not None
                    else None
                ),
                cleanup_attempts=int(row["cleanup_attempts"]),
                lock_id=str(row["lock_id"]) if row["lock_id"] is not None else None,
            ),
            lock_key=lock_key,
            tool_invocation_status=(
                cast(ToolInvocationStatus, str(row["tool_invocation_status"]))
                if row["tool_invocation_status"] is not None
                else None
            ),
        )
        for row in rows
    )


__all__ = ["StoredLockResource", "list_recoverable_workspace_lock_resources"]
