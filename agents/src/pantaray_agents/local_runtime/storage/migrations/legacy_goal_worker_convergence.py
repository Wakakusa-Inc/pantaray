"""Converge active Actions persisted with the retired Goal Worker mode."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass

from .specs import MigrationError

_FAILURE_CODE = "ACTION_ORCHESTRATION_MODE_RETIRED"
_FAILURE_STAGE = "resume_failed"
_FAILURE_MESSAGE = "Action execution failed."
_ACTIVE_ACTION_STATUSES = ("queued", "processing")
_ACTIVE_JOB_STATUSES = ("queued", "running", "paused", "retryable_error", "blocked")
_CONVERGIBLE_PROCESS_STATUSES = ("enqueued", "running", "paused", "abandoned")


@dataclass(frozen=True, slots=True)
class _LegacyAction:
    action_id: str
    user_id: str
    suggestion_id: str | None
    command_id: str
    accepted_at: str
    total_steps: int
    total_llm_steps: int
    total_tool_steps: int
    total_prompt_tokens: int
    total_completion_tokens: int


@dataclass(frozen=True, slots=True)
class _ActiveRuntime:
    job_id: str
    process_id: str
    process_next_event_seq: int


def apply_legacy_goal_worker_convergence_migration(
    connection: sqlite3.Connection,
) -> None:
    connection.row_factory = sqlite3.Row
    actions = _load_legacy_actions(connection)
    if not actions:
        return
    completed_at = str(
        connection.execute("SELECT strftime('%Y-%m-%dT%H:%M:%fZ', 'now')").fetchone()[0]
    )
    for action in actions:
        _converge_action(connection, action, completed_at=completed_at)


def _load_legacy_actions(
    connection: sqlite3.Connection,
) -> tuple[_LegacyAction, ...]:
    rows = connection.execute(
        """
        WITH ranked_checkpoints AS (
            SELECT
                steps.*,
                ROW_NUMBER() OVER (
                    PARTITION BY steps.action_id, steps.user_id
                    ORDER BY steps.step_number DESC,
                             steps.completed_at IS NULL ASC,
                             steps.completed_at DESC,
                             steps.created_at DESC,
                             steps.step_id DESC
                ) AS checkpoint_rank
            FROM agent_action_steps AS steps
            WHERE steps.runtime_state_checkpoint IS NOT NULL
        ),
        current_checkpoints AS (
            SELECT *
            FROM ranked_checkpoints
            WHERE checkpoint_rank = 1
        ),
        ranked_user_steps AS (
            SELECT
                user_steps.*,
                ROW_NUMBER() OVER (
                    PARTITION BY user_steps.action_id, user_steps.user_id
                    ORDER BY user_steps.step_number DESC,
                             user_steps.created_at DESC,
                             user_steps.step_id DESC
                ) AS user_step_rank
            FROM agent_action_steps AS user_steps
            WHERE user_steps.step_type = 'user_request'
              AND user_steps.status = 'success'
        )
        SELECT
            actions.action_id,
            actions.user_id,
            actions.suggestion_id,
            user_steps.user_message_id AS command_id,
            json_extract(
                user_steps.user_message_json,
                '$.message_id'
            ) AS envelope_message_id,
            COALESCE(
                json_extract(
                    user_steps.user_message_json,
                    '$.suggestion_approval.approved_at'
                ),
                user_steps.created_at
            ) AS accepted_at,
            CASE json_type(checkpoints.runtime_state_checkpoint, '$.steps_taken') WHEN 'integer'
                THEN json_extract(checkpoints.runtime_state_checkpoint, '$.steps_taken')
            END AS checkpoint_total_steps,
            CASE json_type(checkpoints.runtime_state_checkpoint, '$.llm_steps_taken') WHEN 'integer'
                THEN json_extract(checkpoints.runtime_state_checkpoint, '$.llm_steps_taken')
            END AS checkpoint_total_llm_steps,
            CASE json_type(checkpoints.runtime_state_checkpoint, '$.tool_steps_taken') WHEN 'integer'
                THEN json_extract(checkpoints.runtime_state_checkpoint, '$.tool_steps_taken')
            END AS checkpoint_total_tool_steps,
            CASE json_type(checkpoints.runtime_state_checkpoint, '$.total_prompt_tokens') WHEN 'integer'
                THEN json_extract(checkpoints.runtime_state_checkpoint, '$.total_prompt_tokens')
            END AS checkpoint_total_prompt_tokens,
            CASE json_type(checkpoints.runtime_state_checkpoint, '$.total_completion_tokens') WHEN 'integer'
                THEN json_extract(checkpoints.runtime_state_checkpoint, '$.total_completion_tokens')
            END AS checkpoint_total_completion_tokens,
            actions.total_steps AS stored_total_steps,
            actions.total_llm_steps AS stored_total_llm_steps,
            actions.total_tool_steps AS stored_total_tool_steps,
            actions.total_prompt_tokens AS stored_total_prompt_tokens,
            actions.total_completion_tokens AS stored_total_completion_tokens
        FROM agent_actions AS actions
        JOIN current_checkpoints AS checkpoints
          ON checkpoints.action_id = actions.action_id
         AND checkpoints.user_id = actions.user_id
        LEFT JOIN ranked_user_steps AS user_steps
          ON user_steps.action_id = actions.action_id
         AND user_steps.user_id = actions.user_id
         AND user_steps.user_step_rank = 1
        WHERE actions.status IN (?, ?)
          AND json_type(
              checkpoints.runtime_state_checkpoint,
              '$.context.use_goal_workers'
          ) = 'true'
          AND (
              user_steps.step_number IS NULL
              OR user_steps.step_number <= checkpoints.step_number
          )
        ORDER BY actions.action_id
        """,
        _ACTIVE_ACTION_STATUSES,
    ).fetchall()
    actions = []
    for row in rows:
        command_id = _required_text(row["command_id"], field_name="command_id")
        if command_id != _required_text(
            row["envelope_message_id"], field_name="envelope_message_id"
        ):
            raise MigrationError(
                "v85 legacy Goal Worker USER message identity is inconsistent: "
                f"action_id={row['action_id']}"
            )
        total_steps = _required_nonnegative_int(
            row["checkpoint_total_steps"], field_name="steps_taken"
        )
        total_llm_steps = _required_nonnegative_int(
            row["checkpoint_total_llm_steps"], field_name="llm_steps_taken"
        )
        total_tool_steps = _required_nonnegative_int(
            row["checkpoint_total_tool_steps"], field_name="tool_steps_taken"
        )
        total_prompt_tokens = _required_nonnegative_int(
            row["checkpoint_total_prompt_tokens"], field_name="total_prompt_tokens"
        )
        total_completion_tokens = _required_nonnegative_int(
            row["checkpoint_total_completion_tokens"],
            field_name="total_completion_tokens",
        )
        if (
            total_steps != total_llm_steps + total_tool_steps
            or total_steps < int(row["stored_total_steps"])
            or total_llm_steps < int(row["stored_total_llm_steps"])
            or total_tool_steps < int(row["stored_total_tool_steps"])
            or total_prompt_tokens < int(row["stored_total_prompt_tokens"])
            or total_completion_tokens < int(row["stored_total_completion_tokens"])
        ):
            raise MigrationError(
                "v85 legacy Goal Worker checkpoint counters are inconsistent: "
                f"action_id={row['action_id']}"
            )
        actions.append(
            _LegacyAction(
                action_id=_required_text(row["action_id"], field_name="action_id"),
                user_id=_required_text(row["user_id"], field_name="user_id"),
                suggestion_id=_optional_text(row["suggestion_id"]),
                command_id=command_id,
                accepted_at=_required_text(
                    row["accepted_at"], field_name="accepted_at"
                ),
                total_steps=total_steps,
                total_llm_steps=total_llm_steps,
                total_tool_steps=total_tool_steps,
                total_prompt_tokens=total_prompt_tokens,
                total_completion_tokens=total_completion_tokens,
            )
        )
    return tuple(actions)


def _load_active_runtime(
    connection: sqlite3.Connection,
    action: _LegacyAction,
) -> _ActiveRuntime:
    placeholders = ", ".join("?" for _ in _ACTIVE_JOB_STATUSES)
    rows = connection.execute(
        f"""
        SELECT
            jobs.job_id,
            jobs.status AS job_status,
            jobs.process_id AS job_process_id,
            processes.process_id,
            processes.status AS process_status,
            processes.suggestion_id AS process_suggestion_id,
            processes.current_job_id,
            processes.next_event_seq
        FROM jobs
        JOIN processes
          ON processes.user_id = jobs.user_id
         AND processes.kind = 'action'
         AND processes.action_id = jobs.logical_key
         AND processes.status IN ({", ".join("?" for _ in _CONVERGIBLE_PROCESS_STATUSES)})
        WHERE jobs.job_type = 'execute_action'
          AND jobs.logical_key = ?
          AND jobs.user_id = ?
          AND jobs.status IN ({placeholders})
        ORDER BY jobs.job_id
        """,
        (
            *_CONVERGIBLE_PROCESS_STATUSES,
            action.action_id,
            action.user_id,
            *_ACTIVE_JOB_STATUSES,
        ),
    ).fetchall()
    if len(rows) != 1:
        raise MigrationError(
            "v85 legacy Goal Worker convergence requires exactly one active "
            f"Action job: action_id={action.action_id} count={len(rows)}"
        )
    row = rows[0]
    job_id = _required_text(row["job_id"], field_name="job_id")
    process_id = _required_text(row["process_id"], field_name="process_id")
    job_status = str(row["job_status"])
    job_process_id = _optional_text(row["job_process_id"])
    if (
        _optional_text(row["process_suggestion_id"]) != action.suggestion_id
        or job_process_id != process_id
    ):
        raise MigrationError(
            "v85 legacy Goal Worker runtime lineage is inconsistent: "
            f"action_id={action.action_id}"
        )
    process_status = str(row["process_status"])
    if process_status == "abandoned" and job_status != "blocked":
        raise MigrationError(
            "v85 legacy Goal Worker abandoned process is not blocked: "
            f"action_id={action.action_id} job_status={job_status}"
        )
    current_job_id = _optional_text(row["current_job_id"])
    expected_current_job_id = job_id if process_status == "running" else None
    if (
        job_status == "blocked"
        and current_job_id not in (None, job_id)
        or job_status != "blocked"
        and current_job_id != expected_current_job_id
    ):
        raise MigrationError(
            "v85 legacy Goal Worker current job ownership is inconsistent: "
            f"action_id={action.action_id} job_status={row['job_status']} "
            f"process_status={process_status}"
        )
    return _ActiveRuntime(
        job_id=job_id,
        process_id=process_id,
        process_next_event_seq=int(row["next_event_seq"]),
    )


def _converge_action(
    connection: sqlite3.Connection,
    action: _LegacyAction,
    *,
    completed_at: str,
) -> None:
    from pantaray_agents.local_runtime.suggestion_state.public_process_events import (
        append_public_process_event,
    )
    from pantaray_agents.local_runtime.suggestion_state.public_projection import (
        EVENT_PROCESS_COMPLETED,
        rebuild_history_projection,
    )

    runtime = _load_active_runtime(connection, action)
    error = {
        "error_code": _FAILURE_CODE,
        "error_type": "resume_error",
        "error_message": _FAILURE_MESSAGE,
        "severity": "error",
    }
    event_data: dict[str, object] = {
        "kind": "action",
        "process_id": runtime.process_id,
        "action_id": action.action_id,
        "command_id": action.command_id,
        "status": "error",
        "completed_at": completed_at,
        "error": error,
        "failure_code": _FAILURE_CODE,
        "failure_stage": _FAILURE_STAGE,
        "failure_message_public": _FAILURE_MESSAGE,
    }
    event_meta: dict[str, object] = {
        "kind": "action",
        "process_id": runtime.process_id,
        "action_id": action.action_id,
        "command_id": action.command_id,
        "failure_code": _FAILURE_CODE,
    }
    if action.suggestion_id is not None:
        event_data["suggestion_id"] = action.suggestion_id
        event_meta["suggestion_id"] = action.suggestion_id
        cursor = connection.execute(
            """
            UPDATE agent_suggestions
            SET accepted_at = ?,
                action_status = 'error',
                action_command_id = ?,
                action_process_id = ?,
                action_failure_code = ?,
                action_failure_stage = ?,
                action_failure_message_public = ?,
                action_request_payload = NULL,
                updated_at = ?
            WHERE suggestion_id = ? AND user_id = ?
              AND EXISTS (
                  SELECT 1 FROM agent_actions AS actions
                  WHERE actions.action_id = ?
                    AND actions.user_id = ?
                    AND actions.suggestion_id = agent_suggestions.suggestion_id
              )
            """,
            (
                action.accepted_at,
                action.command_id,
                runtime.process_id,
                _FAILURE_CODE,
                _FAILURE_STAGE,
                _FAILURE_MESSAGE,
                completed_at,
                action.suggestion_id,
                action.user_id,
                action.action_id,
                action.user_id,
            ),
        )
        _require_single_update(cursor, boundary="suggestion", action=action)
    serialized_error = json.dumps(error, ensure_ascii=False, separators=(",", ":"))
    cursor = connection.execute(
        """
        UPDATE agent_actions
        SET status = 'error', final_output = '', error = ?,
            total_steps = ?, total_llm_steps = ?, total_tool_steps = ?,
            total_prompt_tokens = ?, total_completion_tokens = ?,
            total_tokens = ?, updated_at = ?
        WHERE action_id = ? AND user_id = ? AND status IN (?, ?)
        """,
        (
            serialized_error,
            action.total_steps,
            action.total_llm_steps,
            action.total_tool_steps,
            action.total_prompt_tokens,
            action.total_completion_tokens,
            action.total_prompt_tokens + action.total_completion_tokens,
            completed_at,
            action.action_id,
            action.user_id,
            *_ACTIVE_ACTION_STATUSES,
        ),
    )
    _require_single_update(cursor, boundary="action", action=action)
    connection.execute(
        """
        UPDATE agent_action_steps
        SET status = 'error', completed_at = COALESCE(completed_at, ?), error = ?
        WHERE action_id = ? AND user_id = ?
          AND status IN ('queued', 'processing')
        """,
        (completed_at, serialized_error, action.action_id, action.user_id),
    )
    connection.execute(
        """
        UPDATE approval_sessions
        SET status = 'interrupted', decided_at = ?
        WHERE action_id = ? AND user_id = ? AND status = 'pending'
        """,
        (completed_at, action.action_id, action.user_id),
    )
    connection.execute(
        """
        UPDATE tool_invocations
        SET status = 'canceled', completed_at = ?
        WHERE action_id = ? AND user_id = ? AND status IN ('queued', 'running')
        """,
        (completed_at, action.action_id, action.user_id),
    )
    connection.execute(
        """
        UPDATE execution_sessions
        SET status = 'canceled', completed_at = ?
        WHERE action_id = ? AND user_id = ? AND status = 'running'
        """,
        (completed_at, action.action_id, action.user_id),
    )
    connection.execute(
        """
        UPDATE job_attempts
        SET status = 'failed', completed_at = ?, error_code = ?
        WHERE job_id = ? AND status = 'running'
        """,
        (completed_at, _FAILURE_CODE, runtime.job_id),
    )
    cursor = connection.execute(
        f"""
        UPDATE jobs
        SET status = 'failed', completed_at = ?, heartbeat_at = ?, error_code = ?
        WHERE job_id = ? AND status IN ({", ".join("?" for _ in _ACTIVE_JOB_STATUSES)})
        """,
        (
            completed_at,
            completed_at,
            _FAILURE_CODE,
            runtime.job_id,
            *_ACTIVE_JOB_STATUSES,
        ),
    )
    _require_single_update(cursor, boundary="job", action=action)
    internal_event_id = f"v85-legacy-goal-worker-internal:{runtime.process_id}"
    connection.execute(
        """
        INSERT INTO process_events(
            process_id, event_seq, event_id, event_name, payload_json, created_at
        ) VALUES (?, ?, ?, 'stream_end', ?, ?)
        """,
        (
            runtime.process_id,
            runtime.process_next_event_seq,
            internal_event_id,
            json.dumps(event_data, ensure_ascii=False, separators=(",", ":")),
            completed_at,
        ),
    )
    process_placeholders = ", ".join("?" for _ in _CONVERGIBLE_PROCESS_STATUSES)
    cursor = connection.execute(
        f"""
        UPDATE processes
        SET status = 'failed', completed_at = ?, current_job_id = NULL,
            terminal_event_id = ?, updated_at = ?, heartbeat_at = ?,
            next_event_seq = next_event_seq + 1
        WHERE process_id = ? AND status IN ({process_placeholders})
        """,
        (
            completed_at,
            internal_event_id,
            completed_at,
            completed_at,
            runtime.process_id,
            *_CONVERGIBLE_PROCESS_STATUSES,
        ),
    )
    _require_single_update(cursor, boundary="process", action=action)
    append_public_process_event(
        connection=connection,
        event_id=f"v85-legacy-goal-worker-public:{action.action_id}",
        suggestion_id=action.suggestion_id,
        user_id=action.user_id,
        action_id=action.action_id,
        event_name=EVENT_PROCESS_COMPLETED,
        payload={"data": event_data, "meta": event_meta},
        created_at=completed_at,
    )
    if action.suggestion_id is not None:
        rebuild_history_projection(
            connection=connection,
            user_id=action.user_id,
            suggestion_id=action.suggestion_id,
        )


def _required_text(value: object, *, field_name: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise MigrationError(
            f"v85 legacy Goal Worker convergence requires {field_name}"
        )
    return normalized


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    return _required_text(value, field_name="optional identifier")


def _required_nonnegative_int(value: object, *, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise MigrationError(
            f"v85 legacy Goal Worker checkpoint requires nonnegative {field_name}"
        )
    return value


def _require_single_update(
    cursor: sqlite3.Cursor,
    *,
    boundary: str,
    action: _LegacyAction,
) -> None:
    if cursor.rowcount != 1:
        raise MigrationError(
            "v85 legacy Goal Worker convergence lost its validated "
            f"{boundary}: action_id={action.action_id}"
        )


__all__ = ["apply_legacy_goal_worker_convergence_migration"]
