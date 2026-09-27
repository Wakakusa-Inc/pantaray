from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Literal, NamedTuple, TypedDict

from pantaray_agents.tasks.types import ActionSubagentJobPayload

from ..storage.migrations import MigrationError
from ..storage.migrations.connection import configure_connection
from ..storage.transactions import (
    SQLiteTransactionOwnershipError,
    immediate_transaction,
)
from .job_envelope import (
    LocalJobEnvelope,
    LocalJobEnvelopeIntegrityError,
    load_local_job_envelope,
    require_valid_local_job_envelope,
)
from .job_payload_models import serialize_action_subagent_job_payload
from .job_types import LOCAL_ACTION_SUBAGENT_JOB_TYPE
from .process_events import append_process_event_in_connection
from .utc_timestamps import now_utc_iso

ACTION_SUBAGENT_REPORT_MAX_BYTES = 262_144


class ActionSubagentReportError(ValueError):
    """A private child report does not satisfy its durable bound."""


class ActionSubagentTerminalSuccess(TypedDict):
    outcome: Literal["success"]
    report: str


class ActionSubagentTerminalFailure(TypedDict):
    outcome: Literal["failure"]
    error_code: str


class ActionSubagentTerminalCanceled(TypedDict):
    outcome: Literal["canceled"]


type ActionSubagentTerminalResult = (
    ActionSubagentTerminalSuccess
    | ActionSubagentTerminalFailure
    | ActionSubagentTerminalCanceled
)


class _TerminalAuthority(NamedTuple):
    envelope: LocalJobEnvelope
    current_job_id: str | None
    terminal_event_id: str | None
    process_completed_at: str | None
    cancel_requested_at: str | None
    job_completed_at: str | None
    job_error_code: str | None


def build_action_subagent_success_result(report: str) -> ActionSubagentTerminalSuccess:
    if not report.strip():
        raise ActionSubagentReportError("Action subagent report must not be blank")
    if len(report.encode("utf-8")) > ACTION_SUBAGENT_REPORT_MAX_BYTES:
        raise ActionSubagentReportError(
            "Action subagent report exceeds "
            f"{ACTION_SUBAGENT_REPORT_MAX_BYTES} UTF-8 bytes"
        )
    return {"outcome": "success", "report": report}


def build_action_subagent_failure_result(
    error_code: str,
) -> ActionSubagentTerminalFailure:
    if not error_code.strip():
        raise ActionSubagentReportError("child failure error_code must not be blank")
    return {"outcome": "failure", "error_code": error_code}


def build_action_subagent_canceled_result() -> ActionSubagentTerminalCanceled:
    return {"outcome": "canceled"}


def finalize_action_subagent_terminal(
    *,
    db_path: Path,
    busy_timeout_ms: int,
    payload: ActionSubagentJobPayload,
    result: ActionSubagentTerminalResult,
) -> ActionSubagentTerminalResult:
    """Commit or replay one private child terminal result."""

    if busy_timeout_ms <= 0:
        raise MigrationError("LOCAL_DB_BUSY_TIMEOUT_MS must be a positive integer")
    with sqlite3.connect(db_path) as connection:
        configure_connection(connection, busy_timeout_ms)
        with immediate_transaction(connection):
            return finalize_action_subagent_terminal_in_connection(
                connection=connection,
                payload=payload,
                result=result,
                completed_at=now_utc_iso(),
            )


def finalize_action_subagent_terminal_in_connection(
    *,
    connection: sqlite3.Connection,
    payload: ActionSubagentJobPayload,
    result: ActionSubagentTerminalResult,
    completed_at: str,
) -> ActionSubagentTerminalResult:
    """Settle a child inside the caller's write transaction.

    A queued-cancel caller first sets ``cancel_requested_at`` in this transaction.
    """

    if not connection.in_transaction:
        raise SQLiteTransactionOwnershipError(
            "Action subagent terminal requires a caller-owned transaction"
        )
    authority = _load_authority(connection, payload)
    if authority.envelope.job_status in {"completed", "failed", "canceled"}:
        return _load_terminal_winner(connection, payload, authority)

    winner = (
        build_action_subagent_canceled_result()
        if authority.cancel_requested_at is not None
        else result
    )
    if winner["outcome"] == "canceled" and authority.cancel_requested_at is None:
        raise LocalJobEnvelopeIntegrityError("Subagent cancellation was not requested")
    _validate_active_authority(connection, authority, winner)
    event_id = append_process_event_in_connection(
        connection=connection,
        process_id=payload["process_id"],
        event_name="stream_end",
        payload=dict(winner),
        created_at=completed_at,
    )
    status, error_code = _terminal_status(winner)
    _require_one_updated_row(
        connection.execute(
            """
            UPDATE jobs
            SET status=?,completed_at=?,heartbeat_at=?,error_code=?
            WHERE job_id=? AND user_id=? AND job_type=? AND process_id=?
              AND status=?
            """,
            (
                status,
                completed_at,
                completed_at,
                error_code,
                payload["job_id"],
                payload["user_id"],
                LOCAL_ACTION_SUBAGENT_JOB_TYPE,
                payload["process_id"],
                authority.envelope.job_status,
            ),
        ),
        "job",
    )
    _require_one_updated_row(
        connection.execute(
            """
            UPDATE processes
            SET status=?,completed_at=?,current_job_id=NULL,
                updated_at=?,heartbeat_at=?
            WHERE process_id=? AND user_id=? AND kind='action_subagent'
              AND action_id=? AND parent_process_id=? AND status=?
              AND current_job_id IS ? AND terminal_event_id=?
            """,
            (
                status,
                completed_at,
                completed_at,
                completed_at,
                payload["process_id"],
                payload["user_id"],
                payload["action_id"],
                payload["parent_process_id"],
                authority.envelope.process_status,
                authority.current_job_id,
                event_id,
            ),
        ),
        "process",
    )
    if authority.envelope.job_status == "running":
        _require_one_updated_row(
            connection.execute(
                """
                UPDATE job_attempts
                SET status=?,completed_at=?,error_code=?,error_message=NULL
                WHERE job_id=? AND attempt_number=? AND status='running'
                """,
                (
                    status,
                    completed_at,
                    error_code,
                    payload["job_id"],
                    authority.envelope.attempt,
                ),
            ),
            "attempt",
        )
    released = connection.execute(
        """
        UPDATE action_subagent_resource_claims SET released_at=?
        WHERE user_id=? AND action_id=? AND parent_process_id=?
          AND child_process_id=? AND released_at IS NULL
        """,
        (
            completed_at,
            payload["user_id"],
            payload["action_id"],
            payload["parent_process_id"],
            payload["process_id"],
        ),
    )
    if int(released.rowcount) != len(payload["resource_claim_ids"]):
        raise LocalJobEnvelopeIntegrityError("Subagent claims changed at terminal")
    return winner


def load_action_subagent_terminal_result_in_connection(
    *,
    connection: sqlite3.Connection,
    payload: ActionSubagentJobPayload,
) -> ActionSubagentTerminalResult | None:
    authority = _load_authority(connection, payload)
    if authority.envelope.job_status in {"completed", "failed", "canceled"}:
        return _load_terminal_winner(connection, payload, authority)
    if (
        authority.envelope.job_status in {"queued", "running", "paused"}
        and authority.envelope.process_status in {"enqueued", "running", "paused"}
        and authority.terminal_event_id is None
        and authority.process_completed_at is None
        and authority.job_completed_at is None
    ):
        return None
    raise LocalJobEnvelopeIntegrityError("Subagent nonterminal authority is invalid")


def _load_authority(
    connection: sqlite3.Connection,
    payload: ActionSubagentJobPayload,
) -> _TerminalAuthority:
    envelope = load_local_job_envelope(connection=connection, job_id=payload["job_id"])
    if envelope is None:
        raise LocalJobEnvelopeIntegrityError("Subagent terminal job does not exist")
    require_valid_local_job_envelope(
        envelope,
        expected_job_type=LOCAL_ACTION_SUBAGENT_JOB_TYPE,
        expected_user_id=payload["user_id"],
    )
    row = connection.execute(
        """
        SELECT process.action_id,process.parent_process_id,
               process.current_job_id,process.terminal_event_id,
               process.completed_at,job.cancel_requested_at,
               job.completed_at,job.error_code
        FROM jobs AS job JOIN processes AS process
          ON process.process_id=job.process_id
        WHERE job.job_id=?
        """,
        (payload["job_id"],),
    ).fetchone()
    if row is None or (
        envelope.process_id != payload["process_id"]
        or envelope.logical_key != payload["job_id"]
        or envelope.payload_json != serialize_action_subagent_job_payload(payload)
        or row[0] != payload["action_id"]
        or row[1] != payload["parent_process_id"]
    ):
        raise LocalJobEnvelopeIntegrityError("Subagent terminal authority is invalid")
    return _TerminalAuthority(
        envelope,
        *(str(value) if value is not None else None for value in row[2:]),
    )


def _validate_active_authority(
    connection: sqlite3.Connection,
    authority: _TerminalAuthority,
    winner: ActionSubagentTerminalResult,
) -> None:
    envelope = authority.envelope
    if authority.terminal_event_id is not None:
        raise LocalJobEnvelopeIntegrityError("Active subagent is already terminal")
    if envelope.job_status == "running":
        attempt = connection.execute(
            "SELECT status FROM job_attempts WHERE job_id=? AND attempt_number=?",
            (envelope.job_id, envelope.attempt),
        ).fetchone()
        if (
            envelope.process_status != "running"
            or authority.current_job_id != envelope.job_id
            or envelope.attempt < 1
            or attempt is None
            or tuple(attempt) != ("running",)
        ):
            raise LocalJobEnvelopeIntegrityError(
                "Running subagent authority is invalid"
            )
        return
    attempt = connection.execute(
        "SELECT status FROM job_attempts WHERE job_id=? AND attempt_number=?",
        (envelope.job_id, envelope.attempt),
    ).fetchone()
    if (
        envelope.job_status != "queued"
        or envelope.process_status != "enqueued"
        or authority.current_job_id is not None
        or winner["outcome"] != "canceled"
        or (attempt is None) != (envelope.attempt == 0)
        or (attempt is not None and tuple(attempt) == ("running",))
    ):
        raise LocalJobEnvelopeIntegrityError("Queued subagent authority is invalid")


def _load_terminal_winner(
    connection: sqlite3.Connection,
    payload: ActionSubagentJobPayload,
    authority: _TerminalAuthority,
) -> ActionSubagentTerminalResult:
    if authority.terminal_event_id is None or authority.job_completed_at is None:
        raise LocalJobEnvelopeIntegrityError("Subagent terminal winner is incomplete")
    row = connection.execute(
        """
        SELECT event_name,payload_json,created_at,
               (SELECT COUNT(*) FROM action_subagent_resource_claims
                WHERE user_id=? AND action_id=? AND parent_process_id=?
                  AND child_process_id=? AND released_at IS NULL)
        FROM process_events WHERE process_id=? AND event_id=?
        """,
        (
            payload["user_id"],
            payload["action_id"],
            payload["parent_process_id"],
            payload["process_id"],
            payload["process_id"],
            authority.terminal_event_id,
        ),
    ).fetchone()
    if row is None or row[0] != "stream_end":
        raise LocalJobEnvelopeIntegrityError("Subagent terminal event is invalid")
    winner = _parse_terminal_result(row[1])
    status, error_code = _terminal_status(winner)
    completed_at = str(row[2])
    if (
        authority.envelope.job_status != status
        or authority.envelope.process_status != status
        or authority.current_job_id is not None
        or authority.process_completed_at != completed_at
        or authority.job_completed_at != completed_at
        or authority.job_error_code != error_code
        or int(row[3]) != 0
        or (winner["outcome"] == "canceled")
        != (authority.cancel_requested_at is not None)
    ):
        raise LocalJobEnvelopeIntegrityError("Subagent terminal winner is invalid")
    attempt = connection.execute(
        """SELECT status,completed_at,error_code,error_message FROM job_attempts
        WHERE job_id=? AND attempt_number=?""",
        (authority.envelope.job_id, authority.envelope.attempt),
    ).fetchone()
    actual_attempt = tuple(attempt) if attempt is not None else None
    expected_attempt = (
        None
        if authority.envelope.attempt == 0
        else (status, completed_at, error_code, None)
    )
    queued_history = (
        winner["outcome"] == "canceled"
        and actual_attempt is not None
        and actual_attempt[0] in {"completed", "failed"}
        and actual_attempt[1] is not None
    )
    if actual_attempt != expected_attempt and not queued_history:
        raise LocalJobEnvelopeIntegrityError("Subagent terminal attempt is invalid")
    return winner


def _parse_terminal_result(payload_json: object) -> ActionSubagentTerminalResult:
    try:
        raw: object = (
            json.loads(payload_json) if isinstance(payload_json, str) else None
        )
        if not isinstance(raw, dict):
            raise ValueError
        if raw.keys() == {"outcome", "report"} and raw["outcome"] == "success":
            report = raw["report"]
            if isinstance(report, str):
                return build_action_subagent_success_result(report)
        if raw.keys() == {"outcome", "error_code"} and raw["outcome"] == "failure":
            error_code = raw["error_code"]
            if isinstance(error_code, str):
                return build_action_subagent_failure_result(error_code)
        if raw == {"outcome": "canceled"}:
            return build_action_subagent_canceled_result()
    except ValueError as exc:
        raise LocalJobEnvelopeIntegrityError(
            "Subagent terminal payload is invalid"
        ) from exc
    raise LocalJobEnvelopeIntegrityError("Subagent terminal payload is invalid")


def _terminal_status(result: ActionSubagentTerminalResult) -> tuple[str, str | None]:
    if result["outcome"] == "success":
        return "completed", None
    if result["outcome"] == "failure":
        return "failed", result["error_code"]
    return "canceled", None


def _require_one_updated_row(cursor: sqlite3.Cursor, row_name: str) -> None:
    if int(cursor.rowcount) != 1:
        raise LocalJobEnvelopeIntegrityError(
            f"Subagent terminal {row_name} changed during finalization"
        )
