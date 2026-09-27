"""Durable authority for one Action process bound to a WebSocket relay."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import cast

from pantaray_agents.action_status import ACTION_TERMINAL_STATUSES
from pantaray_agents.local_runtime.runtime import (
    action_message_process_fence as process_lineage,
)
from pantaray_agents.local_runtime.runtime import (
    identity,
    job_payload_models,
    runtime_env,
)
from pantaray_agents.local_runtime.storage.migrations import MigrationError
from pantaray_agents.local_runtime.tooling.resources import resource_db_support
from pantaray_agents.schema.action_conversation import ActionStatus

_ACTION_STATUSES = frozenset({"queued", "processing", *ACTION_TERMINAL_STATUSES})
_ACTIVE_STATUS_TRIPLES = frozenset(
    {
        ("queued", "enqueued", "queued"),
        ("processing", "enqueued", "queued"),
        ("queued", "running", "running"),
        ("processing", "running", "running"),
        ("processing", "paused", "paused"),
        ("processing", "running", "retryable_error"),
    }
)
_TERMINAL_STATUS_PAIRS = frozenset(
    {("completed", "completed"), ("failed", "failed"), ("canceled", "canceled")}
)


class ActionRelayAuthorityError(MigrationError):
    """Raised when durable relay identity is absent or inconsistent."""


@dataclass(frozen=True, slots=True)
class ActionRelayAuthority:
    user_id: str
    action_id: str
    process_id: str
    root_process_id: str
    command_id: str
    suggestion_id: str | None
    action_status: ActionStatus
    terminal_cursor: int | None


def load_action_relay_authority(
    *, user_id: str, action_id: str, process_id: str
) -> ActionRelayAuthority:
    identity.verify_current_owner(user_id)
    db_path, busy_timeout_ms = runtime_env.read_local_runtime_db_config()
    db_uri = f"{db_path.resolve().as_uri()}?mode=ro"
    with sqlite3.connect(db_uri, uri=True) as connection:
        resource_db_support.configure_connection(connection, busy_timeout_ms)
        connection.execute("BEGIN")
        rows = connection.execute(
            """
            SELECT action.suggestion_id, action.status AS action_status, process.suggestion_id AS process_suggestion_id,
                   process.status AS process_status, process.terminal_event_id, terminal.process_event_rowid AS terminal_cursor, job.job_id, job.status AS job_status, payload.payload_json
            FROM agent_actions AS action
            JOIN processes AS process ON process.action_id = action.action_id
              AND process.user_id = action.user_id AND process.kind = 'action'
            JOIN jobs AS job ON job.process_id = process.process_id
              AND job.user_id = action.user_id AND job.job_type = 'execute_action' AND job.logical_key = action.action_id
            JOIN job_payloads AS payload ON payload.job_id = job.job_id
            LEFT JOIN process_events AS terminal ON terminal.process_id = process.process_id
              AND terminal.event_id = process.terminal_event_id AND terminal.event_name = 'stream_end'
            WHERE action.user_id = ? AND action.action_id = ? AND process.process_id = ? LIMIT 2
            """,
            (user_id, action_id, process_id),
        ).fetchall()
        if len(rows) != 1:
            raise ActionRelayAuthorityError("Action relay authority is unavailable")
        row = rows[0]
        job_id = _required_text(row["job_id"])
        payload = job_payload_models.parse_action_job_payload_json(
            _required_text(row["payload_json"])
        )
        if (
            payload["job_id"] != job_id
            or payload["process_id"] != process_id
            or payload["action_id"] != action_id
            or payload["user_id"] != user_id
        ):
            raise ActionRelayAuthorityError("Action relay payload is inconsistent")
        suggestion_id = _optional_text(row["suggestion_id"])
        if _optional_text(row["process_suggestion_id"]) != suggestion_id:
            raise ActionRelayAuthorityError("Action relay Suggestion is inconsistent")

        action_status = _required_text(row["action_status"])
        if action_status not in _ACTION_STATUSES:
            raise ActionRelayAuthorityError("Action relay status is invalid")
        typed_action_status = cast(ActionStatus, action_status)
        runtime_pair = (
            _required_text(row["process_status"]),
            _required_text(row["job_status"]),
        )
        terminal_event_id = row["terminal_event_id"]
        terminal_cursor = row["terminal_cursor"]
        if runtime_pair in _TERMINAL_STATUS_PAIRS:
            _required_text(terminal_event_id)
            if not isinstance(terminal_cursor, int) or terminal_cursor <= 0:
                raise ActionRelayAuthorityError("Action relay terminal is unavailable")
        elif (action_status, *runtime_pair) in _ACTIVE_STATUS_TRIPLES:
            if terminal_event_id is not None or terminal_cursor is not None:
                raise ActionRelayAuthorityError("Active Action has a terminal event")
        else:
            raise ActionRelayAuthorityError("Action relay status is noncanonical")

        lineage = process_lineage.resolve_action_process_lineage_in_connection(
            connection=connection,
            user_id=user_id,
            action_id=action_id,
            process_id=process_id,
        )
        if lineage.job_id != job_id:
            raise ActionRelayAuthorityError("Action relay job lineage is inconsistent")
        user_row = connection.execute(
            """
            SELECT user_message_id
            FROM agent_action_steps
            WHERE user_id = ? AND action_id = ?
              AND step_type = 'user_request' AND status = 'success'
              AND step_number IS NOT NULL AND adopted_process_id = ?
            ORDER BY step_number DESC, created_at DESC, step_id DESC
            LIMIT 1
            """,
            (user_id, action_id, lineage.root_process_id),
        ).fetchone()
        if user_row is None:
            raise ActionRelayAuthorityError("Action relay root USER is unavailable")
        return ActionRelayAuthority(
            user_id=user_id,
            action_id=action_id,
            process_id=process_id,
            root_process_id=lineage.root_process_id,
            command_id=_required_text(user_row["user_message_id"]),
            suggestion_id=suggestion_id,
            action_status=typed_action_status,
            terminal_cursor=terminal_cursor,
        )


def _required_text(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ActionRelayAuthorityError("Action relay identity is incomplete")
    return value


def _optional_text(value: object) -> str | None:
    return None if value is None else _required_text(value)
