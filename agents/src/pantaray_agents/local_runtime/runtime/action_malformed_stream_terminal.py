from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from pantaray_agents.action_status import (
    ACTION_STATUS_ERROR,
    ActionTerminalStatus,
    build_finalize_action_terminal_command,
)
from pantaray_agents.local_runtime.storage.migrations import MigrationError
from pantaray_agents.local_runtime.storage.transactions import immediate_transaction
from pantaray_agents.local_runtime.suggestion_state.shared import configure_connection

from .action_job_runtime_repository import (
    load_and_validate_action_command_user_step_in_connection,
)
from .action_message_process_fence import (
    resolve_action_process_lineage_in_connection,
)
from .action_terminal_handoff import (
    apply_action_terminal_handoff_in_connection,
    validate_action_terminal_handoff_in_connection,
)
from .action_terminal_repository import (
    action_run_terminal_is_pending_in_connection,
    finalize_action_job_terminal_in_connection,
)


@dataclass(frozen=True, slots=True)
class MalformedActionStreamTerminalResult:
    terminal_status: ActionTerminalStatus
    terminal_event_id: str
    emit_invalid_payload_error: bool


@dataclass(frozen=True, slots=True)
class ActionMalformedStreamTerminalRepository:
    db_path: Path
    busy_timeout_ms: int

    def finalize(
        self,
        *,
        user_id: str,
        suggestion_id: str | None,
        action_id: str,
        process_id: str,
        command_id: str,
        malformed_event_id: str,
        completed_at: str,
        failure_code: str,
        failure_message_public: str,
    ) -> MalformedActionStreamTerminalResult:
        if self.busy_timeout_ms <= 0:
            raise MigrationError("LOCAL_DB_BUSY_TIMEOUT_MS must be a positive integer")

        with sqlite3.connect(self.db_path) as connection:
            configure_connection(connection, self.busy_timeout_ms)
            with immediate_transaction(connection):
                lineage = resolve_action_process_lineage_in_connection(
                    connection=connection,
                    user_id=user_id,
                    action_id=action_id,
                    process_id=process_id,
                )
                action_row = connection.execute(
                    """
                    SELECT suggestion_id, initial_user_message_id, execution_target_json
                    FROM agent_actions
                    WHERE action_id = ? AND user_id = ? AND suggestion_id IS ?
                    """,
                    (action_id, user_id, suggestion_id),
                ).fetchone()
                if action_row is None:
                    raise MigrationError(
                        "Malformed Action stream owner is inconsistent"
                    )
                context = load_and_validate_action_command_user_step_in_connection(
                    connection=connection,
                    action_row=action_row,
                    user_id=user_id,
                    action_id=action_id,
                    process_id=lineage.root_process_id,
                    command_id=command_id,
                )
                if context.suggestion_id != suggestion_id:
                    raise MigrationError(
                        "Malformed Action stream Suggestion is inconsistent"
                    )
                command = build_finalize_action_terminal_command(
                    process_completed_event_id=f"{process_id}:invalid-payload",
                    user_id=user_id,
                    suggestion_id=suggestion_id,
                    accepted_at=context.accepted_at,
                    command_id=command_id,
                    process_id=process_id,
                    action_id=action_id,
                    completed_at=completed_at,
                    action_status=ACTION_STATUS_ERROR,
                    failure_code=failure_code,
                    failure_stage="running_failed",
                    failure_message_public=failure_message_public,
                )
                _remove_owned_malformed_stream_end(
                    connection=connection,
                    user_id=user_id,
                    suggestion_id=suggestion_id,
                    action_id=action_id,
                    process_id=process_id,
                    job_id=lineage.job_id,
                    malformed_event_id=malformed_event_id,
                )
                if not action_run_terminal_is_pending_in_connection(
                    connection=connection,
                    command=command,
                    job_id=lineage.job_id,
                    physical_run_only=False,
                ):
                    status, event_id = _read_existing_terminal(
                        connection=connection,
                        process_id=process_id,
                    )
                    return MalformedActionStreamTerminalResult(
                        terminal_status=status,
                        terminal_event_id=event_id,
                        emit_invalid_payload_error=False,
                    )

                authority = validate_action_terminal_handoff_in_connection(
                    connection=connection,
                    command=command,
                    job_id=lineage.job_id,
                )
                finalize_action_job_terminal_in_connection(
                    connection=connection,
                    command=command,
                    job_id=lineage.job_id,
                )
                apply_action_terminal_handoff_in_connection(
                    connection=connection,
                    command=command,
                    authority=authority,
                    runtime_state_checkpoint=None,
                )
                return MalformedActionStreamTerminalResult(
                    terminal_status=ACTION_STATUS_ERROR,
                    terminal_event_id=command.process_completed_event_id,
                    emit_invalid_payload_error=True,
                )


def _remove_owned_malformed_stream_end(
    *,
    connection: sqlite3.Connection,
    user_id: str,
    suggestion_id: str | None,
    action_id: str,
    process_id: str,
    job_id: str,
    malformed_event_id: str,
) -> None:
    row = connection.execute(
        """
        SELECT process.status, process.completed_at, process.current_job_id,
               process.terminal_event_id, event.event_name
        FROM processes AS process
        LEFT JOIN process_events AS event
          ON event.process_id = process.process_id AND event.event_id = ?
        WHERE process.process_id = ? AND process.user_id = ?
          AND process.kind = 'action' AND process.action_id = ?
          AND process.suggestion_id IS ?
        """,
        (malformed_event_id, process_id, user_id, action_id, suggestion_id),
    ).fetchone()
    if row is None:
        raise MigrationError("Malformed Action stream event owner is inconsistent")
    if row["event_name"] is None:
        if (
            row["status"] in {"completed", "failed", "canceled"}
            and isinstance(row["completed_at"], str)
            and row["current_job_id"] is None
            and isinstance(row["terminal_event_id"], str)
        ):
            return
        raise MigrationError("Active malformed Action stream event is unavailable")
    if (
        row["event_name"] != "stream_end"
        or row["status"] != "running"
        or row["completed_at"] is not None
        or row["current_job_id"] != job_id
        or row["terminal_event_id"] != malformed_event_id
    ):
        raise MigrationError("Malformed Action stream_end is not replaceable")
    cleared = connection.execute(
        """
        UPDATE processes SET terminal_event_id = NULL
        WHERE process_id = ? AND terminal_event_id = ?
        """,
        (process_id, malformed_event_id),
    )
    deleted = connection.execute(
        """
        DELETE FROM process_events
        WHERE process_id = ? AND event_id = ? AND event_name = 'stream_end'
        """,
        (process_id, malformed_event_id),
    )
    if cleared.rowcount != 1 or deleted.rowcount != 1:
        raise MigrationError("Malformed Action stream_end replacement lost ownership")


def _read_existing_terminal(
    *, connection: sqlite3.Connection, process_id: str
) -> tuple[ActionTerminalStatus, str]:
    row = connection.execute(
        "SELECT status, terminal_event_id FROM processes WHERE process_id = ?",
        (process_id,),
    ).fetchone()
    if row is None or not isinstance(row["terminal_event_id"], str):
        raise MigrationError("Malformed Action stream terminal is unavailable")
    status_by_process = {
        "completed": "success",
        "failed": "error",
        "canceled": "canceled",
    }
    status = status_by_process.get(str(row["status"]))
    if status is None:
        raise MigrationError("Malformed Action stream terminal status is inconsistent")
    return status, row["terminal_event_id"]


__all__ = [
    "ActionMalformedStreamTerminalRepository",
    "MalformedActionStreamTerminalResult",
]
