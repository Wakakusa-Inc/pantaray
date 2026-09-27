from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import cast

from pantaray_agents.schema.read_access import ReadAccessScope

from ...storage.migrations import MigrationError
from ...storage.transactions import immediate_transaction
from ...storage.users import ensure_user_row
from ..action_file_read_memory import register_action_file_read_memory
from ..action_subagent_resource_authority import (
    record_command_write_authority_in_connection,
)
from ..models import (
    EXECUTION_SESSION_TERMINAL_STATUSES,
    ExecutionMode,
    ExecutionSessionCreateInput,
    ExecutionSessionStatus,
    ExecutionSessionTerminalStatus,
    StoredExecutionSession,
    ToolInvocationCompletionContext,
    ToolInvocationCompletionInput,
    ToolInvocationStartInput,
)
from .action_file_references import (
    _record_tool_invocation_file_references_in_connection,
)
from .common import (
    _configure_connection,
    _deserialize_json_string_map,
    _serialize_json,
)


class ExecutionSessionParentConflictError(MigrationError):
    """Raised when a child cannot bind to its live parent session."""


class ExecutionSessionNotFoundError(MigrationError):
    """Raised when a requested execution-session transition has no owner row."""


class ExecutionSessionCompletionStatusError(ValueError):
    """Raised when completion is requested with a non-terminal status."""


class ExecutionSessionTerminalStateError(RuntimeError):
    """Raised when a terminal execution session cannot transition again."""

    def __init__(
        self,
        *,
        execution_session_id: str,
        current_status: str,
        requested_status: str,
    ) -> None:
        super().__init__(
            "execution session completion rejected: session is already terminal "
            f"(execution_session_id={execution_session_id} "
            f"current_status={current_status} requested_status={requested_status})"
        )
        self.execution_session_id = execution_session_id
        self.current_status = current_status
        self.requested_status = requested_status


class ToolInvocationSessionConflictError(MigrationError):
    """Raised when invocation creation cannot bind to its live session."""


class ToolInvocationTerminalStateError(RuntimeError):
    """Raised when a late completion races with an existing terminal state."""

    def __init__(
        self,
        *,
        invocation_id: str,
        current_status: str,
        requested_status: str,
    ) -> None:
        super().__init__(
            "tool invocation completion rejected: invocation is already terminal "
            f"(invocation_id={invocation_id} current_status={current_status} "
            f"requested_status={requested_status})"
        )
        self.invocation_id = invocation_id
        self.current_status = current_status
        self.requested_status = requested_status


def _resolve_existing_action_id(
    connection: sqlite3.Connection,
    *,
    user_id: str,
    action_id: str | None,
) -> str | None:
    if action_id is None:
        return None
    existing = connection.execute(
        "SELECT action_id FROM agent_actions WHERE action_id = ? AND user_id = ?",
        (action_id, user_id),
    ).fetchone()
    if existing is not None:
        return action_id
    raise MigrationError(
        "tooling action context missing: action row not found for action_id"
    )


def _ensure_action_step_row(
    connection: sqlite3.Connection,
    *,
    step_id: str | None,
) -> str | None:
    if step_id is None:
        return None
    existing = connection.execute(
        "SELECT step_id FROM agent_action_steps WHERE step_id = ?",
        (step_id,),
    ).fetchone()
    if existing is not None:
        return step_id
    return None


def load_execution_session(
    *,
    db_path: Path,
    busy_timeout_ms: int,
    execution_session_id: str,
) -> StoredExecutionSession:
    with sqlite3.connect(db_path) as connection:
        _configure_connection(connection=connection, busy_timeout_ms=busy_timeout_ms)
        row = connection.execute(
            """
            SELECT
                execution_session_id,
                action_id,
                user_id,
                status,
                exec_mode,
                cwd_path,
                action_temp_dir,
                app_runtime_python,
                network_policy,
                read_access_scope,
                capability_snapshot_json,
                tool_allowlist_json
            FROM execution_sessions
            WHERE execution_session_id = ?
            """,
            (execution_session_id,),
        ).fetchone()
    if row is None:
        raise MigrationError(f"execution session not found: {execution_session_id}")
    tool_allowlist_json = (
        json.loads(str(row["tool_allowlist_json"]))
        if row["tool_allowlist_json"] is not None
        else None
    )
    return StoredExecutionSession(
        execution_session_id=str(row["execution_session_id"]),
        action_id=str(row["action_id"]) if row["action_id"] is not None else None,
        user_id=str(row["user_id"]),
        status=cast(ExecutionSessionStatus, str(row["status"])),
        exec_mode=cast(ExecutionMode, str(row["exec_mode"])),
        cwd_path=str(row["cwd_path"]),
        action_temp_dir=(
            str(row["action_temp_dir"]) if row["action_temp_dir"] is not None else None
        ),
        app_runtime_python=(
            str(row["app_runtime_python"])
            if row["app_runtime_python"] is not None
            else None
        ),
        network_policy=str(row["network_policy"]),
        read_access_scope=cast(ReadAccessScope, str(row["read_access_scope"])),
        capability_snapshot_json=_deserialize_json_string_map(
            row["capability_snapshot_json"], field_name="capability_snapshot_json"
        ),
        tool_allowlist_json=tool_allowlist_json,
    )


def load_action_job_root_execution_session_id(
    *,
    db_path: Path,
    busy_timeout_ms: int,
    job_id: str,
    process_id: str,
    user_id: str,
    action_id: str,
) -> str | None:
    with sqlite3.connect(
        f"{db_path.resolve().as_uri()}?mode=ro", uri=True
    ) as connection:
        _configure_connection(connection=connection, busy_timeout_ms=busy_timeout_ms)
        connection.execute("PRAGMA query_only = ON")
        row = connection.execute(
            """
            SELECT session.execution_session_id
            FROM jobs AS job
            JOIN processes AS process ON process.process_id = job.process_id
            JOIN agent_actions AS action ON action.action_id = process.action_id
            JOIN workspace_manifests AS manifest ON manifest.action_id = action.action_id
              AND manifest.user_id = action.user_id
            JOIN execution_sessions AS session ON session.execution_session_id = manifest.execution_session_id
            WHERE job.job_id = :job_id AND job.process_id = :process_id
              AND job.user_id = :user_id
              AND job.job_type = 'execute_action' AND job.status = 'running'
              AND job.logical_key = :action_id
              AND process.user_id = :user_id AND process.kind = 'action'
              AND process.status = 'running'
              AND process.action_id = :action_id AND process.current_job_id = :job_id
              AND action.user_id = :user_id AND manifest.status = 'ready'
              AND session.user_id = :user_id AND session.action_id = :action_id
              AND session.parent_execution_session_id IS NULL
            """,
            {
                "action_id": action_id,
                "job_id": job_id,
                "process_id": process_id,
                "user_id": user_id,
            },
        ).fetchone()
    return str(row["execution_session_id"]) if row is not None else None


def create_execution_session(
    *,
    db_path: Path,
    busy_timeout_ms: int,
    session: ExecutionSessionCreateInput,
) -> None:
    with sqlite3.connect(db_path) as connection:
        _configure_connection(connection=connection, busy_timeout_ms=busy_timeout_ms)
        with connection:
            create_execution_session_in_connection(
                connection=connection,
                session=session,
            )


def create_execution_session_in_connection(
    *,
    connection: sqlite3.Connection,
    session: ExecutionSessionCreateInput,
) -> None:
    ensure_user_row(
        connection,
        user_id=session.user_id,
        timestamp=session.started_at,
    )
    action_id = _resolve_existing_action_id(
        connection,
        user_id=session.user_id,
        action_id=session.action_id,
    )
    cursor = connection.execute(
        """
        INSERT INTO execution_sessions(
            execution_session_id,
            user_id,
            action_id,
            parent_execution_session_id,
            exec_mode,
            cwd_path,
            action_temp_dir,
            app_runtime_python,
            network_policy,
            read_access_scope,
            capability_snapshot_json,
            tool_allowlist_json,
            status,
            started_at,
            completed_at,
            expires_at
        )
        SELECT ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?
        FROM (SELECT 1) AS candidate
        LEFT JOIN execution_sessions AS parent
          ON parent.execution_session_id = ?
        LEFT JOIN agent_actions AS root_action
          ON root_action.action_id = ? AND root_action.user_id = ?
        WHERE
            (? IS NULL AND (? IS NULL OR root_action.status = 'processing'))
            OR (
                parent.execution_session_id IS NOT NULL
                AND parent.status = 'running'
                AND parent.user_id = ?
                AND parent.action_id IS ?
            )
        """,
        (
            session.execution_session_id,
            session.user_id,
            action_id,
            session.parent_execution_session_id,
            session.exec_mode,
            session.cwd_path,
            session.action_temp_dir,
            session.app_runtime_python,
            session.network_policy,
            session.read_access_scope,
            _serialize_json(session.capability_snapshot_json),
            (
                _serialize_json(session.tool_allowlist_json)
                if session.tool_allowlist_json is not None
                else None
            ),
            session.status,
            session.started_at,
            session.expires_at,
            session.parent_execution_session_id,
            action_id,
            session.user_id,
            session.parent_execution_session_id,
            action_id,
            session.user_id,
            action_id,
        ),
    )
    if cursor.rowcount != 1:
        raise ExecutionSessionParentConflictError(
            "execution session creation rejected: an Action root requires a processing "
            "Action, and a child requires an exactly matching running parent"
        )


def complete_execution_session(
    *,
    db_path: Path,
    busy_timeout_ms: int,
    execution_session_id: str,
    status: ExecutionSessionTerminalStatus,
    completed_at: str,
) -> None:
    if status not in EXECUTION_SESSION_TERMINAL_STATUSES:
        raise ExecutionSessionCompletionStatusError(
            "execution session completion requires a terminal status"
        )
    with sqlite3.connect(db_path) as connection:
        _configure_connection(connection=connection, busy_timeout_ms=busy_timeout_ms)
        with connection:
            cursor = connection.execute(
                """
                UPDATE execution_sessions
                SET status = ?, completed_at = ?
                WHERE execution_session_id = ? AND status = 'running'
                """,
                (status, completed_at, execution_session_id),
            )
            if cursor.rowcount == 1:
                return
            row = connection.execute(
                """
                SELECT status
                FROM execution_sessions
                WHERE execution_session_id = ?
                """,
                (execution_session_id,),
            ).fetchone()
            if row is None:
                raise ExecutionSessionNotFoundError(
                    f"execution session not found: {execution_session_id}"
                )
            raise ExecutionSessionTerminalStateError(
                execution_session_id=execution_session_id,
                current_status=str(row["status"]),
                requested_status=status,
            )


def record_tool_invocation_start(
    *,
    db_path: Path,
    busy_timeout_ms: int,
    invocation: ToolInvocationStartInput,
) -> None:
    with sqlite3.connect(db_path) as connection:
        _configure_connection(connection=connection, busy_timeout_ms=busy_timeout_ms)
        with immediate_transaction(connection):
            _record_tool_invocation_start_in_connection(
                connection=connection,
                invocation=invocation,
            )


def _record_tool_invocation_start_in_connection(
    *,
    connection: sqlite3.Connection,
    invocation: ToolInvocationStartInput,
) -> None:
    step_id = _ensure_action_step_row(
        connection,
        step_id=invocation.step_id,
    )
    cursor = connection.execute(
        """
        INSERT INTO tool_invocations(
            invocation_id,
            user_id,
            action_id,
            step_id,
            tool_id,
            manifest_id,
            execution_session_id,
            cwd,
            timeout_ms,
            intent_class,
            network_policy,
            command_summary_json,
            capability_snapshot_json,
            tool_request_id,
            status,
            started_at,
            completed_at
        )
        SELECT ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL
        FROM execution_sessions AS session
        JOIN workspace_manifests AS manifest ON manifest.manifest_id = ?
        WHERE session.execution_session_id = ?
          AND session.status = 'running'
          AND session.user_id = ?
          AND session.action_id IS ?
          AND manifest.status = 'ready'
          AND manifest.user_id = session.user_id
          AND manifest.action_id = session.action_id
          AND manifest.execution_session_id = session.execution_session_id
        """,
        (
            invocation.invocation_id,
            invocation.user_id,
            invocation.action_id,
            step_id,
            invocation.tool_id,
            invocation.manifest_id,
            invocation.execution_session_id,
            invocation.cwd,
            invocation.timeout_ms,
            invocation.intent_class,
            invocation.network_policy,
            (
                _serialize_json(invocation.command_summary_json)
                if invocation.command_summary_json is not None
                else None
            ),
            (
                _serialize_json(invocation.capability_snapshot_json)
                if invocation.capability_snapshot_json is not None
                else None
            ),
            invocation.tool_request_id,
            invocation.status,
            invocation.started_at,
            invocation.manifest_id,
            invocation.execution_session_id,
            invocation.user_id,
            invocation.action_id,
        ),
    )
    if cursor.rowcount != 1:
        raise ToolInvocationSessionConflictError(
            "tool invocation creation rejected: session must be running and exactly "
            "match the invocation owner and current ready manifest"
        )
    record_command_write_authority_in_connection(connection, invocation)


def load_tool_invocation_completion_context(
    *,
    db_path: Path,
    busy_timeout_ms: int,
    invocation_id: str,
) -> ToolInvocationCompletionContext:
    with sqlite3.connect(db_path) as connection:
        _configure_connection(connection=connection, busy_timeout_ms=busy_timeout_ms)
        row = connection.execute(
            """
            SELECT
                i.tool_id,
                i.user_id,
                i.action_id,
                i.manifest_id
            FROM tool_invocations AS i
            WHERE i.invocation_id = ?
            """,
            (invocation_id,),
        ).fetchone()
    if row is None:
        raise MigrationError(
            f"tool invocation completion context not found: {invocation_id}"
        )
    return ToolInvocationCompletionContext(
        tool_id=str(row["tool_id"]),
        user_id=str(row["user_id"]),
        action_id=str(row["action_id"]),
        manifest_id=str(row["manifest_id"]),
    )


def record_tool_invocation_completion(
    *,
    db_path: Path,
    busy_timeout_ms: int,
    completion: ToolInvocationCompletionInput,
) -> None:
    with sqlite3.connect(db_path) as connection:
        _configure_connection(connection=connection, busy_timeout_ms=busy_timeout_ms)
        with immediate_transaction(connection):
            invocation_row = connection.execute(
                """
                SELECT invocation_id, user_id, status
                FROM tool_invocations
                WHERE invocation_id = ?
                """,
                (completion.invocation_id,),
            ).fetchone()
            if invocation_row is None:
                raise MigrationError(
                    "tool invocation completion failed: invocation not found"
                )
            current_status = str(invocation_row["status"])
            if current_status not in {"queued", "running"}:
                raise ToolInvocationTerminalStateError(
                    invocation_id=completion.invocation_id,
                    current_status=current_status,
                    requested_status=completion.status,
                )
            cursor = connection.execute(
                """
                UPDATE tool_invocations
                SET status = ?, completed_at = ?
                WHERE invocation_id = ?
                  AND status IN ('queued', 'running')
                """,
                (
                    completion.status,
                    completion.completed_at,
                    completion.invocation_id,
                ),
            )
            if cursor.rowcount != 1:
                latest_row = connection.execute(
                    "SELECT status FROM tool_invocations WHERE invocation_id = ?",
                    (completion.invocation_id,),
                ).fetchone()
                latest_status = (
                    str(latest_row["status"]) if latest_row is not None else "missing"
                )
                raise ToolInvocationTerminalStateError(
                    invocation_id=completion.invocation_id,
                    current_status=latest_status,
                    requested_status=completion.status,
                )
            connection.execute(
                """
                INSERT INTO tool_outputs(
                    output_id,
                    invocation_id,
                    search_text,
                    stdout_text,
                    stderr_text,
                    output_json,
                    output_storage_kind,
                    redaction_applied,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    completion.invocation_id,
                    completion.invocation_id,
                    completion.search_text,
                    completion.stdout_text,
                    completion.stderr_text,
                    _serialize_json(completion.output_json),
                    completion.output_storage_kind,
                    1 if completion.redaction_applied else 0,
                    completion.completed_at,
                ),
            )
            register_action_file_read_memory(
                connection=connection,
                invocation_id=completion.invocation_id,
                user_id=str(invocation_row["user_id"]),
                completed_at=completion.completed_at,
                read_memory=completion.read_memory,
                redaction_applied=completion.redaction_applied,
            )
            if completion.file_references:
                _record_tool_invocation_file_references_in_connection(
                    connection=connection,
                    invocation_id=completion.invocation_id,
                    file_references=completion.file_references,
                )
