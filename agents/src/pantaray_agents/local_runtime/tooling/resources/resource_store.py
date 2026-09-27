from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from pantaray_agents.action_status import ACTION_STATUS_PROCESSING

from ...storage.migrations import MigrationError
from ...storage.transactions import immediate_transaction
from ..models import (
    StoredToolRuntimeResource,
    ToolRuntimeResourceCreateInput,
    ToolRuntimeResourceStatus,
)
from .resource_db_support import build_tool_runtime_resource, configure_connection

TERMINAL_RESOURCE_STATUSES: tuple[ToolRuntimeResourceStatus, ...] = (
    "cleaned",
    "abandoned",
)


class ToolRuntimeResourceSessionConflictError(MigrationError):
    """Raised when resource creation cannot bind to its live session owner."""


@dataclass(frozen=True, slots=True)
class ActionSessionTempCleanupCandidate:
    user_id: str
    action_id: str
    execution_session_id: str


def create_tool_runtime_resource(
    *,
    db_path: Path,
    busy_timeout_ms: int,
    resource: ToolRuntimeResourceCreateInput,
) -> None:
    with sqlite3.connect(db_path) as connection:
        configure_connection(connection, busy_timeout_ms)
        with immediate_transaction(connection):
            create_tool_runtime_resource_in_connection(
                connection=connection,
                resource=resource,
            )


def create_tool_runtime_resource_in_connection(
    *,
    connection: sqlite3.Connection,
    resource: ToolRuntimeResourceCreateInput,
) -> None:
    _validate_process_group_registration_in_connection(
        connection=connection,
        resource=resource,
    )
    cursor = connection.execute(
        """
        INSERT INTO tool_runtime_resources(
            resource_id,
            execution_session_id,
            tool_invocation_id,
            action_id,
            resource_kind,
            status,
            pid,
            pgid,
            process_start_signature,
            resource_path,
            lock_id,
            created_at,
            updated_at,
            cleaned_at,
            cleanup_error,
            cleanup_attempts
        )
        SELECT ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, 0
        FROM execution_sessions AS session
        LEFT JOIN tool_invocations AS invocation
          ON invocation.invocation_id = ?
        WHERE session.execution_session_id = ?
          AND session.status = 'running'
          AND session.action_id IS ?
          AND (
              (? IS NULL AND invocation.invocation_id IS NULL)
              OR (
                  invocation.execution_session_id = session.execution_session_id
                  AND invocation.user_id = session.user_id
                  AND invocation.action_id IS session.action_id
                  AND invocation.status IN ('queued', 'running')
              )
          )
        """,
        (
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
            resource.created_at,
            resource.tool_invocation_id,
            resource.execution_session_id,
            resource.action_id,
            resource.tool_invocation_id,
        ),
    )
    if cursor.rowcount != 1:
        raise ToolRuntimeResourceSessionConflictError(
            "tool runtime resource creation rejected: session and optional invocation "
            "must be running and exactly owned"
        )


def load_tool_runtime_resource(
    *,
    db_path: Path,
    busy_timeout_ms: int,
    resource_id: str,
) -> StoredToolRuntimeResource:
    database_uri = f"{db_path.resolve().as_uri()}?mode=ro"
    with sqlite3.connect(database_uri, uri=True) as connection:
        configure_connection(connection, busy_timeout_ms)
        return _load_tool_runtime_resource_in_connection(
            connection=connection,
            resource_id=resource_id,
        )


def _validate_process_group_registration_in_connection(
    *,
    connection: sqlite3.Connection,
    resource: ToolRuntimeResourceCreateInput,
) -> None:
    if resource.resource_kind != "process_group":
        return
    if resource.action_id is not None:
        action_row = connection.execute(
            "SELECT status FROM agent_actions WHERE action_id = ?",
            (resource.action_id,),
        ).fetchone()
        if (
            action_row is None
            or str(action_row["status"]).strip().lower() != ACTION_STATUS_PROCESSING
        ):
            raise MigrationError(
                "process-group resource registration requires a processing Action"
            )


def mark_tool_runtime_resource_cleaned(
    *,
    db_path: Path,
    busy_timeout_ms: int,
    resource_id: str,
    cleaned_at: str,
) -> None:
    _update_tool_runtime_resource_status(
        db_path=db_path,
        busy_timeout_ms=busy_timeout_ms,
        resource_id=resource_id,
        status="cleaned",
        timestamp=cleaned_at,
        cleanup_error=None,
    )


def mark_tool_runtime_resource_cleanup_failed(
    *,
    db_path: Path,
    busy_timeout_ms: int,
    resource_id: str,
    failed_at: str,
    cleanup_error: str,
) -> None:
    _update_tool_runtime_resource_status(
        db_path=db_path,
        busy_timeout_ms=busy_timeout_ms,
        resource_id=resource_id,
        status="cleanup_failed",
        timestamp=failed_at,
        cleanup_error=cleanup_error,
    )


def mark_tool_runtime_resource_abandoned(
    *,
    db_path: Path,
    busy_timeout_ms: int,
    resource_id: str,
    abandoned_at: str,
    cleanup_error: str,
) -> None:
    _update_tool_runtime_resource_status(
        db_path=db_path,
        busy_timeout_ms=busy_timeout_ms,
        resource_id=resource_id,
        status="abandoned",
        timestamp=abandoned_at,
        cleanup_error=cleanup_error,
    )


def list_recoverable_tool_runtime_resources(
    *,
    db_path: Path,
    busy_timeout_ms: int,
) -> tuple[StoredToolRuntimeResource, ...]:
    return _list_recoverable_resources(
        db_path=db_path,
        busy_timeout_ms=busy_timeout_ms,
        where_clause=(
            "(status IN ('active', 'cleanup_failed') OR "
            "(resource_kind = 'process_group' AND status = 'abandoned')) AND NOT "
            "(resource_kind = 'temp_dir' AND action_id IS NOT NULL "
            "AND tool_invocation_id IS NULL)"
        ),
        parameters=(),
    )


def list_periodic_recoverable_tool_runtime_resources(
    *,
    db_path: Path,
    busy_timeout_ms: int,
) -> tuple[StoredToolRuntimeResource, ...]:
    """Return resources whose owning work is already terminal.

    The periodic reaper runs in the same process as live tool execution.  It must
    never infer that an invocation is orphaned merely because it is currently
    marked ``queued`` or ``running``.  In-flight invocation recovery belongs to
    startup, cancellation, and timeout ownership paths.
    """

    with sqlite3.connect(db_path) as connection:
        configure_connection(connection, busy_timeout_ms)
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
                resource.cleanup_attempts
            FROM tool_runtime_resources AS resource
            LEFT JOIN tool_invocations AS invocation
              ON invocation.invocation_id = resource.tool_invocation_id
            JOIN execution_sessions AS session
              ON session.execution_session_id = resource.execution_session_id
            WHERE resource.status IN ('active', 'cleanup_failed', 'abandoned')
              AND (resource.status != 'abandoned'
                   OR resource.resource_kind = 'process_group')
              AND NOT (resource.resource_kind = 'temp_dir'
                       AND resource.action_id IS NOT NULL
                       AND resource.tool_invocation_id IS NULL)
              AND (
                    (
                        resource.tool_invocation_id IS NOT NULL
                        AND invocation.status IN (
                            'completed', 'failed', 'canceled', 'timed_out'
                        )
                    )
                    OR (
                        resource.tool_invocation_id IS NULL
                        AND session.status IN (
                            'completed', 'failed', 'canceled', 'expired'
                        )
                    )
                  )
            ORDER BY resource.created_at ASC
            """
        ).fetchall()
    return tuple(build_tool_runtime_resource(row) for row in rows)


def list_terminal_action_session_temp_cleanup_candidates(
    *,
    db_path: Path,
    busy_timeout_ms: int,
) -> tuple[ActionSessionTempCleanupCandidate, ...]:
    with sqlite3.connect(db_path) as connection:
        configure_connection(connection, busy_timeout_ms)
        rows = connection.execute(
            """
            WITH RECURSIVE session_ancestors(
                user_id, action_id, execution_session_id,
                parent_execution_session_id, depth
            ) AS (
                SELECT DISTINCT session.user_id, session.action_id,
                       session.execution_session_id,
                       session.parent_execution_session_id, 0
                FROM tool_runtime_resources AS resource
                JOIN execution_sessions AS session
                  ON session.execution_session_id = resource.execution_session_id
                JOIN agent_actions AS action
                  ON action.action_id = session.action_id
                 AND action.user_id = session.user_id
                WHERE resource.resource_kind = 'temp_dir'
                  AND resource.action_id = session.action_id
                  AND resource.tool_invocation_id IS NULL
                  AND resource.status IN ('active', 'cleanup_failed')
                  AND session.status IN (
                      'completed', 'failed', 'canceled', 'expired'
                  )
                  AND NOT EXISTS (
                      SELECT 1
                      FROM jobs AS job
                      JOIN processes AS process
                        ON process.process_id = job.process_id
                      JOIN workspace_manifests AS manifest
                        ON manifest.user_id = session.user_id
                       AND manifest.action_id = session.action_id
                       AND manifest.execution_session_id = session.execution_session_id
                       AND manifest.status = 'ready'
                      WHERE job.user_id = session.user_id
                        AND job.job_type = 'execute_action'
                        AND job.status = 'running'
                        AND job.logical_key = session.action_id
                        AND process.user_id = session.user_id
                        AND process.kind = 'action'
                        AND process.status = 'running'
                        AND process.action_id = session.action_id
                        AND process.current_job_id = job.job_id
                  )
                UNION ALL
                SELECT ancestor.user_id, ancestor.action_id,
                       ancestor.execution_session_id,
                       parent.parent_execution_session_id,
                       ancestor.depth + 1
                FROM session_ancestors AS ancestor
                JOIN execution_sessions AS parent
                  ON parent.execution_session_id = ancestor.parent_execution_session_id
                 AND parent.user_id = ancestor.user_id
                 AND parent.action_id = ancestor.action_id
            )
            SELECT user_id, action_id, execution_session_id
            FROM session_ancestors
            WHERE parent_execution_session_id IS NULL
            ORDER BY user_id, action_id, depth DESC, execution_session_id
            """
        ).fetchall()
    return tuple(
        ActionSessionTempCleanupCandidate(
            user_id=str(row["user_id"]),
            action_id=str(row["action_id"]),
            execution_session_id=str(row["execution_session_id"]),
        )
        for row in rows
    )


def list_recoverable_tool_runtime_resources_for_action(
    *,
    db_path: Path,
    busy_timeout_ms: int,
    action_id: str,
    execution_session_id: str | None = None,
) -> tuple[StoredToolRuntimeResource, ...]:
    where_clause = (
        "action_id = ? AND (status IN ('active', 'cleanup_failed') OR "
        "(resource_kind = 'process_group' AND status = 'abandoned'))"
    )
    parameters: tuple[object, ...] = (action_id,)
    if execution_session_id is not None:
        where_clause += (
            " AND execution_session_id = ? AND NOT "
            "(resource_kind = 'temp_dir' AND tool_invocation_id IS NULL)"
        )
        parameters += (execution_session_id,)
    return _list_recoverable_resources(
        db_path=db_path,
        busy_timeout_ms=busy_timeout_ms,
        where_clause=where_clause,
        parameters=parameters,
    )


def list_recoverable_tool_runtime_resources_for_invocation(
    *,
    db_path: Path,
    busy_timeout_ms: int,
    invocation_id: str,
) -> tuple[StoredToolRuntimeResource, ...]:
    return _list_recoverable_resources(
        db_path=db_path,
        busy_timeout_ms=busy_timeout_ms,
        where_clause="tool_invocation_id = ? AND status IN ('active', 'cleanup_failed')",
        parameters=(invocation_id,),
    )


def _list_recoverable_resources(
    *,
    db_path: Path,
    busy_timeout_ms: int,
    where_clause: str,
    parameters: tuple[object, ...],
) -> tuple[StoredToolRuntimeResource, ...]:
    with sqlite3.connect(db_path) as connection:
        configure_connection(connection, busy_timeout_ms)
        rows = connection.execute(
            f"""
            SELECT
                resource_id,
                execution_session_id,
                tool_invocation_id,
                action_id,
                resource_kind,
                status,
                pid,
                pgid,
                process_start_signature,
                resource_path,
                lock_id,
                created_at,
                updated_at,
                cleaned_at,
                cleanup_error,
                cleanup_attempts
            FROM tool_runtime_resources
            WHERE {where_clause}
            ORDER BY created_at ASC
            """,
            parameters,
        ).fetchall()
    return tuple(build_tool_runtime_resource(row) for row in rows)


def _update_tool_runtime_resource_status(
    *,
    db_path: Path,
    busy_timeout_ms: int,
    resource_id: str,
    status: ToolRuntimeResourceStatus,
    timestamp: str,
    cleanup_error: str | None,
) -> None:
    with sqlite3.connect(db_path) as connection:
        configure_connection(connection, busy_timeout_ms)
        with connection:
            _update_tool_runtime_resource_status_in_connection(
                connection=connection,
                resource_id=resource_id,
                status=status,
                timestamp=timestamp,
                cleanup_error=cleanup_error,
            )


def _update_tool_runtime_resource_status_in_connection(
    *,
    connection: sqlite3.Connection,
    resource_id: str,
    status: ToolRuntimeResourceStatus,
    timestamp: str,
    cleanup_error: str | None,
) -> None:
    cursor = connection.execute(
        """
        UPDATE tool_runtime_resources
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
          AND status NOT IN ('cleaned', 'abandoned')
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
    if cursor.rowcount == 1:
        return
    row = connection.execute(
        "SELECT status FROM tool_runtime_resources WHERE resource_id = ?",
        (resource_id,),
    ).fetchone()
    if row is None:
        raise MigrationError(
            "tool runtime resource status update failed: resource does not exist"
        )
    if str(row["status"]) not in TERMINAL_RESOURCE_STATUSES:
        raise MigrationError(
            "tool runtime resource status update failed: expected exactly one row"
        )


def _compare_and_update_tool_runtime_resource_status_in_connection(
    *,
    connection: sqlite3.Connection,
    resource: StoredToolRuntimeResource,
    status: ToolRuntimeResourceStatus,
    timestamp: str,
    cleanup_error: str | None,
) -> bool:
    cursor = connection.execute(
        """
        UPDATE tool_runtime_resources
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
          AND status = ?
          AND updated_at = ?
          AND cleanup_attempts = ?
          AND status NOT IN ('cleaned', 'abandoned')
        """,
        (
            status,
            timestamp,
            status,
            timestamp,
            cleanup_error,
            status,
            resource.resource_id,
            resource.status,
            resource.updated_at,
            resource.cleanup_attempts,
        ),
    )
    return cursor.rowcount == 1


def _load_tool_runtime_resource_in_connection(
    *,
    connection: sqlite3.Connection,
    resource_id: str,
) -> StoredToolRuntimeResource:
    row = connection.execute(
        """
        SELECT
            resource_id,
            execution_session_id,
            tool_invocation_id,
            action_id,
            resource_kind,
            status,
            pid,
            pgid,
            process_start_signature,
            resource_path,
            lock_id,
            created_at,
            updated_at,
            cleaned_at,
            cleanup_error,
            cleanup_attempts
        FROM tool_runtime_resources
        WHERE resource_id = ?
        """,
        (resource_id,),
    ).fetchone()
    if row is None:
        raise MigrationError("tool runtime resource does not exist")
    return build_tool_runtime_resource(row)
