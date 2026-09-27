"""Resolve the process and job authority of selected Action logical runs.

A logical run is the USER-origin process that rooted it: an approval
continuation resumes that same process rather than appending another one. The
read model needs the run's start, current status, and terminal from it, so this
module binds them in one caller-owned snapshot.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from typing import cast

from pantaray_agents.action_status import (
    ActionTerminalStatus,
    FinalizeActionTerminalCommand,
    build_finalize_action_terminal_command,
)
from pantaray_agents.local_runtime.storage.migrations import MigrationError
from pantaray_agents.schema.agent.base import JSONValue

from .action_message_process_disposition import (
    ACTIVE_ACTION_DISPOSITIONS,
    classify_action_status_pair,
)
from .job_payload_models import parse_action_job_payload_json

_TERMINAL_STATUS_BY_AUTHORITY: dict[tuple[str, str], ActionTerminalStatus] = {
    ("completed", "completed"): "success",
    ("failed", "failed"): "error",
    ("canceled", "canceled"): "canceled",
}


@dataclass(frozen=True, slots=True)
class ActionLogicalRunSelection:
    action_id: str
    root_process_id: str


@dataclass(frozen=True, slots=True)
class ActionLogicalRunAuthority:
    action_id: str
    root_process_id: str
    root_accepted_sequence: int
    root_started_at: str
    process_status: str
    job_id: str
    job_status: str
    completed_at: str | None
    terminal_event_id: str | None
    terminal_event_payload_json: str | None


def parse_action_run_terminal_command(
    *,
    user_id: str,
    action_id: str,
    suggestion_id: str | None,
    authority: ActionLogicalRunAuthority,
) -> FinalizeActionTerminalCommand:
    """Validate the stored terminal independently of any conversation display."""
    if (
        not isinstance(authority.completed_at, str)
        or not isinstance(authority.terminal_event_id, str)
        or not isinstance(authority.terminal_event_payload_json, str)
    ):
        raise MigrationError("Terminal Action run has no exact terminal authority")
    if action_id != authority.action_id:
        raise MigrationError("Action terminal authority belongs to another Action")
    status = _TERMINAL_STATUS_BY_AUTHORITY.get(
        (authority.process_status, authority.job_status)
    )
    if status is None:
        raise MigrationError("Action terminal process and job status are inconsistent")
    try:
        decoded = json.loads(authority.terminal_event_payload_json)
    except json.JSONDecodeError as exc:
        raise MigrationError("Action terminal payload is invalid JSON") from exc
    if not isinstance(decoded, dict) or "physical_run_only" in decoded:
        raise MigrationError("Action terminal payload is not public authority")
    payload = dict(decoded)
    sequence = payload.pop("persisted_sequence", None)
    if not isinstance(sequence, int) or isinstance(sequence, bool) or sequence <= 0:
        raise MigrationError("Action terminal persisted_sequence is invalid")
    try:
        command = build_finalize_action_terminal_command(
            process_completed_event_id=authority.terminal_event_id,
            suggestion_id=suggestion_id,
            user_id=user_id,
            command_id=cast(str, payload.get("command_id")),
            process_id=authority.root_process_id,
            action_id=authority.action_id,
            accepted_at=authority.root_started_at,
            completed_at=authority.completed_at,
            action_status=status,
            final_output=cast(str | None, payload.get("final_output")),
            failure_code=cast(str | None, payload.get("failure_code")),
            error_payload=cast(dict[str, JSONValue] | None, payload.get("error")),
            failure_stage=cast(str | None, payload.get("failure_stage")),
            failure_message_public=cast(
                str | None, payload.get("failure_message_public")
            ),
        )
    except ValueError as exc:
        raise MigrationError(
            "Action terminal payload violates the canonical shape"
        ) from exc
    if payload != command.process_completed_payload["data"]:
        raise MigrationError("Action terminal payload identity is inconsistent")
    return command


@dataclass(frozen=True, slots=True)
class _SelectedLogicalRun:
    action_id: str
    process_id: str
    accepted_sequence: int
    started_at: str
    process_status: str
    job_id: str
    job_status: str
    process_completed_at: str | None
    job_completed_at: str | None
    terminal_event_id: str | None


def select_action_logical_run_authorities_in_connection(
    *,
    connection: sqlite3.Connection,
    user_id: str,
    selections: frozenset[ActionLogicalRunSelection],
) -> tuple[ActionLogicalRunAuthority, ...]:
    """Return exact process and job authority for selected logical runs."""

    if not connection.in_transaction:
        raise MigrationError(
            "Action logical run authority requires a caller-owned transaction"
        )
    if not selections:
        return ()
    ordered = tuple(
        sorted(selections, key=lambda item: (item.action_id, item.root_process_id))
    )
    selected_runs = _load_selected_logical_runs(
        connection=connection,
        user_id=user_id,
        selections=ordered,
    )
    terminal_bindings = tuple(
        (
            run.action_id,
            run.process_id,
            _required_text(run.terminal_event_id, field_name="terminal event_id"),
        )
        for run in selected_runs
        if (
            classify_action_status_pair(run.process_status, run.job_status).disposition
            not in ACTIVE_ACTION_DISPOSITIONS
        )
    )
    terminal_events = _load_selected_terminal_events(
        connection=connection,
        user_id=user_id,
        bindings=terminal_bindings,
    )
    return tuple(
        _build_selected_authority(
            run=run,
            terminal_event=terminal_events.get((run.action_id, run.process_id)),
        )
        for run in selected_runs
    )


def _load_selected_logical_runs(
    *,
    connection: sqlite3.Connection,
    user_id: str,
    selections: tuple[ActionLogicalRunSelection, ...],
) -> tuple[_SelectedLogicalRun, ...]:
    parameters: dict[str, str] = {"user_id": user_id}
    for index, selection in enumerate(selections):
        parameters[f"action_{index}"] = selection.action_id
        parameters[f"root_{index}"] = selection.root_process_id
    values = ", ".join(
        f"(:action_{index}, :root_{index})" for index in range(len(selections))
    )
    rows = connection.execute(
        f"""
        WITH selected(action_id, process_id) AS (VALUES {values})
        SELECT selected.action_id,
               selected.process_id,
               process.status AS process_status,
               process.started_at,
               process.completed_at AS process_completed_at,
               process.terminal_event_id,
               job.job_id,
               job.user_id AS job_user_id,
               job.job_type,
               job.logical_key,
               job.status AS job_status,
               job.completed_at AS job_completed_at,
               payload.payload_json,
               (
                   SELECT MIN(steps.accepted_sequence)
                   FROM agent_action_steps AS steps
                   WHERE steps.user_id = :user_id
                     AND steps.action_id = selected.action_id
                     AND steps.adopted_process_id = selected.process_id
                     AND steps.step_type = 'user_request'
                     AND steps.status = 'success'
               ) AS accepted_sequence
        FROM selected
        JOIN processes AS process
          ON process.process_id = selected.process_id
         AND process.user_id = :user_id
         AND process.kind = 'action'
         AND process.action_id = selected.action_id
        JOIN jobs AS job ON job.process_id = selected.process_id
        LEFT JOIN job_payloads AS payload ON payload.job_id = job.job_id
        ORDER BY selected.action_id, selected.process_id, job.job_id
        """,
        parameters,
    ).fetchall()
    if len(rows) != len(selections):
        raise MigrationError("Selected Action logical run envelope is not singular")

    selected_runs: list[_SelectedLogicalRun] = []
    action_sequences: set[tuple[str, int]] = set()
    for row in rows:
        action_id = _required_text(row["action_id"], field_name="action_id")
        process_id = _required_text(row["process_id"], field_name="process_id")
        job_id = _required_text(row["job_id"], field_name="job_id")
        if (
            row["job_user_id"] != user_id
            or row["job_type"] != "execute_action"
            or row["logical_key"] != action_id
        ):
            raise MigrationError("Selected Action process envelope is inconsistent")
        payload_json = _required_text(row["payload_json"], field_name="job payload")
        payload = parse_action_job_payload_json(payload_json)
        if (
            payload["job_id"] != job_id
            or payload["process_id"] != process_id
            or payload["action_id"] != action_id
            or payload["user_id"] != user_id
        ):
            raise MigrationError("Selected Action job payload identity is inconsistent")
        accepted_sequence = row["accepted_sequence"]
        if (
            not isinstance(accepted_sequence, int)
            or isinstance(accepted_sequence, bool)
            or accepted_sequence <= 0
            or (action_id, accepted_sequence) in action_sequences
        ):
            raise MigrationError("Selected Action root USER sequence is inconsistent")
        action_sequences.add((action_id, accepted_sequence))
        selected_runs.append(
            _SelectedLogicalRun(
                action_id=action_id,
                process_id=process_id,
                accepted_sequence=accepted_sequence,
                started_at=_required_text(row["started_at"], field_name="started_at"),
                process_status=_required_text(
                    row["process_status"], field_name="process status"
                ),
                job_id=job_id,
                job_status=_required_text(row["job_status"], field_name="job status"),
                process_completed_at=row["process_completed_at"],
                job_completed_at=row["job_completed_at"],
                terminal_event_id=row["terminal_event_id"],
            )
        )
    return tuple(
        sorted(selected_runs, key=lambda run: (run.action_id, run.accepted_sequence))
    )


def _load_selected_terminal_events(
    *,
    connection: sqlite3.Connection,
    user_id: str,
    bindings: tuple[tuple[str, str, str], ...],
) -> dict[tuple[str, str], tuple[str, str]]:
    if not bindings:
        return {}
    values = ", ".join("(?, ?, ?)" for _binding in bindings)
    parameters = tuple(value for binding in bindings for value in binding)
    rows = connection.execute(
        f"""
        WITH selected(action_id, process_id, event_id) AS (VALUES {values})
        SELECT selected.action_id, events.process_id,
               events.payload_json, events.created_at
        FROM selected
        JOIN processes AS process
          ON process.process_id = selected.process_id
         AND process.action_id = selected.action_id
         AND process.user_id = ?
         AND process.kind = 'action'
        JOIN process_events AS events
          ON events.process_id = selected.process_id
         AND events.event_id = selected.event_id
        WHERE events.event_name = 'stream_end'
        """,
        (*parameters, user_id),
    ).fetchall()
    return {
        (
            _required_text(row["action_id"], field_name="terminal action_id"),
            _required_text(row["process_id"], field_name="terminal process_id"),
        ): (
            _required_text(row["payload_json"], field_name="terminal event payload"),
            _required_text(row["created_at"], field_name="terminal event created_at"),
        )
        for row in rows
    }


def _build_selected_authority(
    *,
    run: _SelectedLogicalRun,
    terminal_event: tuple[str, str] | None,
) -> ActionLogicalRunAuthority:
    disposition = classify_action_status_pair(
        run.process_status, run.job_status
    ).disposition
    completed_at = run.process_completed_at
    if disposition in ACTIVE_ACTION_DISPOSITIONS:
        if any(
            value is not None
            for value in (
                completed_at,
                run.job_completed_at,
                run.terminal_event_id,
            )
        ):
            raise MigrationError("Active Action logical run has terminal metadata")
    else:
        completed_at = _required_text(completed_at, field_name="process completed_at")
        if terminal_event is None:
            raise MigrationError("Action logical run terminal event is missing")
        job_completed_at = _required_text(
            run.job_completed_at, field_name="job completed_at"
        )
        if completed_at != terminal_event[1] or completed_at != job_completed_at:
            raise MigrationError(
                "Action logical run terminal timestamps are inconsistent"
            )
    return ActionLogicalRunAuthority(
        action_id=run.action_id,
        root_process_id=run.process_id,
        root_accepted_sequence=run.accepted_sequence,
        root_started_at=run.started_at,
        process_status=run.process_status,
        job_id=run.job_id,
        job_status=run.job_status,
        completed_at=completed_at,
        terminal_event_id=run.terminal_event_id,
        terminal_event_payload_json=(
            terminal_event[0] if terminal_event is not None else None
        ),
    )


def _required_text(value: object, *, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise MigrationError(f"Action logical run {field_name} is incomplete")
    return value


__all__ = [
    "ActionLogicalRunAuthority",
    "ActionLogicalRunSelection",
    "parse_action_run_terminal_command",
    "select_action_logical_run_authorities_in_connection",
]
