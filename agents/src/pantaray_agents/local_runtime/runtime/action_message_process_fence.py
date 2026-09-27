"""Resolve one Action process to its immutable USER-origin logical run."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from pantaray_agents.local_runtime.storage.migrations import MigrationError
from pantaray_agents.tasks.types import ActionContinuationRef

from .action_message_models import ExpectedProcessConflictError
from .job_payload_models import parse_action_job_payload_json


@dataclass(frozen=True, slots=True)
class ActionLogicalRunLineage:
    root_process_id: str
    root_accepted_sequence: int
    job_id: str


@dataclass(frozen=True, slots=True)
class _ActionProcessEnvelope:
    job_id: str
    continuation: ActionContinuationRef | None


def resolve_action_process_lineage_in_connection(
    *,
    connection: sqlite3.Connection,
    user_id: str,
    action_id: str,
    process_id: str,
) -> ActionLogicalRunLineage:
    """Resolve one exact Action process to its USER-origin logical run."""

    return _resolve_action_process_lineage(
        connection=connection,
        user_id=user_id,
        action_id=action_id,
        process_id=process_id,
        missing_is_expected_conflict=False,
    )


def validate_expected_process_owner_in_connection(
    *,
    connection: sqlite3.Connection,
    user_id: str,
    action_id: str,
    expected_process_id: str | None,
) -> None:
    """Require a non-null fence to name this Action's USER-origin root process."""

    if expected_process_id is None:
        return
    _resolve_action_process_lineage(
        connection=connection,
        user_id=user_id,
        action_id=action_id,
        process_id=expected_process_id,
        missing_is_expected_conflict=True,
    )


def _resolve_action_process_lineage(
    *,
    connection: sqlite3.Connection,
    user_id: str,
    action_id: str,
    process_id: str,
    missing_is_expected_conflict: bool,
) -> ActionLogicalRunLineage:
    # Approval resume reuses the paused process, so every Action process is the
    # USER-origin root of exactly one logical run.
    envelope = _load_action_process_envelope(
        connection=connection,
        user_id=user_id,
        action_id=action_id,
        process_id=process_id,
        missing_is_expected_conflict=missing_is_expected_conflict,
    )
    adopted_sequence = _load_adopted_root_sequence(
        connection=connection,
        user_id=user_id,
        action_id=action_id,
        process_id=process_id,
    )
    if adopted_sequence is not None:
        return ActionLogicalRunLineage(
            root_process_id=process_id,
            root_accepted_sequence=adopted_sequence,
            job_id=envelope.job_id,
        )
    continuation = envelope.continuation
    if continuation is None:
        raise MigrationError("Action process job payload is missing")
    if continuation["kind"] != "user_step":
        raise MigrationError("Action process has no USER-origin logical run root")
    return ActionLogicalRunLineage(
        root_process_id=process_id,
        root_accepted_sequence=_validate_root_user_step(
            connection=connection,
            user_id=user_id,
            action_id=action_id,
            user_step_id=continuation["user_step_id"],
        ),
        job_id=envelope.job_id,
    )


def _load_action_process_envelope(
    *,
    connection: sqlite3.Connection,
    user_id: str,
    action_id: str,
    process_id: str,
    missing_is_expected_conflict: bool,
) -> _ActionProcessEnvelope:
    rows = connection.execute(
        """
        SELECT jobs.job_id, jobs.user_id AS job_user_id,
               jobs.job_type, jobs.logical_key, payloads.payload_json
        FROM processes
        LEFT JOIN jobs ON jobs.process_id = processes.process_id
        LEFT JOIN job_payloads AS payloads ON payloads.job_id = jobs.job_id
        WHERE processes.process_id = ? AND processes.user_id = ?
          AND processes.action_id = ? AND processes.kind = 'action'
        LIMIT 2
        """,
        (process_id, user_id, action_id),
    ).fetchall()
    if not rows:
        if missing_is_expected_conflict:
            raise ExpectedProcessConflictError(
                "process_id is not an Action process for the expected owner"
            )
        raise MigrationError("Action process lineage owner is missing or inconsistent")
    if len(rows) != 1:
        raise MigrationError("Action process does not have exactly one owning job")
    row = rows[0]
    job_id = _required_text(row["job_id"], field_name="job_id")
    if (
        row["job_user_id"] != user_id
        or row["job_type"] != "execute_action"
        or row["logical_key"] != action_id
    ):
        raise MigrationError("Action process job envelope is inconsistent")
    payload_json = row["payload_json"]
    if payload_json is None:
        return _ActionProcessEnvelope(job_id=job_id, continuation=None)
    if not isinstance(payload_json, str):
        raise MigrationError("Action process job payload must be TEXT")
    payload = parse_action_job_payload_json(payload_json)
    if (
        payload["job_id"] != job_id
        or payload["process_id"] != process_id
        or payload["action_id"] != action_id
        or payload["user_id"] != user_id
    ):
        raise MigrationError("Action process job envelope is inconsistent")
    return _ActionProcessEnvelope(
        job_id=job_id,
        continuation=payload["continuation_ref"],
    )


def _load_adopted_root_sequence(
    *,
    connection: sqlite3.Connection,
    user_id: str,
    action_id: str,
    process_id: str,
) -> int | None:
    # Root USER and later steers intentionally share this process; MIN orders the run.
    row = connection.execute(
        """
        SELECT MIN(accepted_sequence)
        FROM agent_action_steps
        WHERE user_id = ? AND action_id = ? AND adopted_process_id = ?
          AND step_type = 'user_request' AND status = 'success'
        """,
        (user_id, action_id, process_id),
    ).fetchone()
    accepted_sequence = row[0]
    if accepted_sequence is None:
        return None
    if not isinstance(accepted_sequence, int) or accepted_sequence <= 0:
        raise MigrationError("Action root USER accepted_sequence must be positive")
    return accepted_sequence


def _validate_root_user_step(
    *,
    connection: sqlite3.Connection,
    user_id: str,
    action_id: str,
    user_step_id: str,
) -> int:
    rows = connection.execute(
        """
        SELECT accepted_sequence
        FROM agent_action_steps
        WHERE step_id = ? AND user_id = ? AND action_id = ?
          AND step_type = 'user_request' AND status = 'success'
        """,
        (user_step_id, user_id, action_id),
    ).fetchall()
    if len(rows) != 1:
        raise MigrationError(
            "Action process does not resolve to one successful USER step"
        )
    accepted_sequence = rows[0]["accepted_sequence"]
    if not isinstance(accepted_sequence, int) or accepted_sequence <= 0:
        raise MigrationError("Action root USER accepted_sequence must be positive")
    return accepted_sequence


def _required_text(value: object, *, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise MigrationError(f"Action lineage {field_name} is incomplete")
    return value


__all__ = [
    "ActionLogicalRunLineage",
    "resolve_action_process_lineage_in_connection",
    "validate_expected_process_owner_in_connection",
]
