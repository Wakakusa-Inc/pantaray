import json
import sqlite3

from .action_creation_cutover_inflight_validation import (
    InflightActionLineage,
    cutover_internal_event_id,
    cutover_public_event_id,
    load_validated_inflight_action_lineages,
)
from .specs import MigrationError

_FAILURE_CODE = "ACTION_CREATION_CUTOVER"
_FAILURE_STAGE = "resume_failed"
_FAILURE_MESSAGE = "Action execution could not be resumed after a local data upgrade."
_PROMPT_NAME = "action_creation_cutover"
_PROMPT_VERSION = "1"


def converge_inflight_actions_for_cutover(connection: sqlite3.Connection) -> None:
    lineages = load_validated_inflight_action_lineages(connection)
    if not lineages:
        return
    completed_at = str(
        connection.execute("SELECT strftime('%Y-%m-%dT%H:%M:%fZ', 'now')").fetchone()[0]
    )
    for lineage in lineages:
        _converge_lineage(connection, lineage, completed_at=completed_at)


def _converge_lineage(
    connection: sqlite3.Connection,
    lineage: InflightActionLineage,
    *,
    completed_at: str,
) -> None:
    from pantaray_agents.local_runtime.suggestion_state import public_projection

    assert lineage.job_id is not None
    error_payload = {
        "error_code": _FAILURE_CODE,
        "error_type": "runtime_error",
        "error_message": _FAILURE_MESSAGE,
        "severity": "error",
    }
    event_data = {
        "kind": "action",
        "process_id": lineage.process_id,
        "suggestion_id": lineage.suggestion_id,
        "action_id": lineage.action_id,
        "command_id": lineage.command_id,
        "status": "error",
        "completed_at": completed_at,
        "error": error_payload,
        "failure_code": _FAILURE_CODE,
        "failure_stage": _FAILURE_STAGE,
        "failure_message_public": _FAILURE_MESSAGE,
    }
    event_payload = json.dumps(
        {
            "data": event_data,
            "meta": {
                "kind": "action",
                "process_id": lineage.process_id,
                "suggestion_id": lineage.suggestion_id,
                "action_id": lineage.action_id,
                "command_id": lineage.command_id,
                "failure_code": _FAILURE_CODE,
            },
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )
    serialized_error = json.dumps(error_payload, separators=(",", ":"))
    connection.execute(
        """
        UPDATE agent_suggestions
        SET action_status = 'error',
            action_failure_code = ?,
            action_failure_stage = ?,
            action_failure_message_public = ?,
            action_request_payload = NULL,
            updated_at = ?
        WHERE suggestion_id = ? AND user_id = ?
        """,
        (
            _FAILURE_CODE,
            _FAILURE_STAGE,
            _FAILURE_MESSAGE,
            completed_at,
            lineage.suggestion_id,
            lineage.user_id,
        ),
    )
    if lineage.action_status == "idle":
        connection.execute(
            """
            INSERT INTO agent_actions(
                action_id, user_id, suggestion_id, status, final_output, error,
                prompt_name, prompt_version, created_at, updated_at
            ) VALUES (?, ?, ?, 'error', '', ?, ?, ?, ?, ?)
            """,
            (
                lineage.action_id,
                lineage.user_id,
                lineage.suggestion_id,
                serialized_error,
                _PROMPT_NAME,
                _PROMPT_VERSION,
                lineage.accepted_at,
                completed_at,
            ),
        )
    else:
        connection.execute(
            """
            UPDATE agent_actions
            SET status = 'error', error = ?, updated_at = ?
            WHERE action_id = ? AND user_id = ? AND status = 'processing'
            """,
            (serialized_error, completed_at, lineage.action_id, lineage.user_id),
        )
    connection.execute(
        """
        UPDATE agent_action_steps
        SET status = 'error', completed_at = ?, error = ?
        WHERE action_id = ? AND status = 'processing'
        """,
        (
            completed_at,
            serialized_error,
            lineage.action_id,
        ),
    )
    connection.execute(
        """
        UPDATE approval_sessions
        SET status = 'interrupted', decided_at = ?
        WHERE action_id = ? AND status = 'pending'
        """,
        (completed_at, lineage.action_id),
    )
    connection.execute(
        """
        UPDATE tool_invocations
        SET status = 'canceled', completed_at = ?
        WHERE action_id = ? AND status IN ('queued', 'running')
        """,
        (completed_at, lineage.action_id),
    )
    connection.execute(
        """
        UPDATE execution_sessions
        SET status = 'canceled', completed_at = ?
        WHERE action_id = ? AND status = 'running'
        """,
        (completed_at, lineage.action_id),
    )
    connection.execute(
        """
        UPDATE job_attempts
        SET status = 'failed', completed_at = ?, error_code = ?
        WHERE job_id = ? AND status = 'running'
        """,
        (completed_at, _FAILURE_CODE, lineage.job_id),
    )
    connection.execute(
        """
        UPDATE jobs
        SET status = 'failed', completed_at = ?, heartbeat_at = ?, error_code = ?
        WHERE job_id = ?
        """,
        (completed_at, completed_at, _FAILURE_CODE, lineage.job_id),
    )
    internal_event_id = cutover_internal_event_id(lineage.process_id)
    process_row = connection.execute(
        "SELECT next_event_seq FROM processes WHERE process_id = ?",
        (lineage.process_id,),
    ).fetchone()
    if process_row is None:
        raise MigrationError(
            f"v82 convergence lost validated process: {lineage.process_id}"
        )
    connection.execute(
        """
        INSERT INTO process_events(
            process_id, event_seq, event_id, event_name, payload_json, created_at
        ) VALUES (?, ?, ?, 'stream_end', ?, ?)
        """,
        (
            lineage.process_id,
            int(process_row["next_event_seq"]),
            internal_event_id,
            json.dumps(event_data, ensure_ascii=False, separators=(",", ":")),
            completed_at,
        ),
    )
    connection.execute(
        """
        UPDATE processes
        SET status = 'failed', completed_at = ?, current_job_id = NULL,
            terminal_event_id = ?, updated_at = ?, heartbeat_at = ?,
            next_event_seq = next_event_seq + 1
        WHERE process_id = ?
        """,
        (
            completed_at,
            internal_event_id,
            completed_at,
            completed_at,
            lineage.process_id,
        ),
    )
    public_sequence = int(
        connection.execute(
            """
            SELECT COALESCE(MAX(sequence), 0) + 1
            FROM agent_process_events
            WHERE suggestion_id = ?
            """,
            (lineage.suggestion_id,),
        ).fetchone()[0]
    )
    connection.execute(
        """
        INSERT INTO agent_process_events(
            event_id, suggestion_id, user_id, action_id, sequence,
            event_name, payload, created_at
        ) VALUES (?, ?, ?, ?, ?, 'process_completed', ?, ?)
        """,
        (
            cutover_public_event_id(lineage.suggestion_id),
            lineage.suggestion_id,
            lineage.user_id,
            lineage.action_id,
            public_sequence,
            event_payload,
            completed_at,
        ),
    )
    public_projection.rebuild_history_projection(
        connection=connection,
        user_id=lineage.user_id,
        suggestion_id=lineage.suggestion_id,
    )
