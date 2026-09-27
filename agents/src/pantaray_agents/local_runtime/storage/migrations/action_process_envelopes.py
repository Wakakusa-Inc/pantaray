"""Load structural Action process evidence for USER lineage migration."""

from __future__ import annotations

import json
import re
import sqlite3
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import NamedTuple, cast

from .specs import MigrationError

ACTION_PAYLOAD_FIELDS = frozenset(
    {"job_id", "process_id", "action_id", "user_id", "continuation_ref"}
)
USER_STEP_CONTINUATION_FIELDS = frozenset({"kind", "user_step_id"})
TOOL_APPROVAL_CONTINUATION_FIELDS = frozenset(
    {"kind", "approval_session_id", "tool_request_id"}
)
TERMINAL_JOB_STATUSES = frozenset({"completed", "failed", "abandoned", "canceled"})
TERMINAL_PROCESS_STATUSES = frozenset({"completed", "failed", "canceled"})
V85_FAILURE_CODE = "ACTION_ORCHESTRATION_MODE_RETIRED"
V85_FAILURE_STAGE = "resume_failed"
V85_FAILURE_MESSAGE = "Action execution failed."
V85_MIGRATION_NAME = "0085_legacy_goal_worker_convergence.sql"
V85_ERROR_FIELDS = frozenset({"error_code", "error_type", "error_message", "severity"})
V85_EVENT_FIELDS = frozenset(
    {
        "kind",
        "process_id",
        "action_id",
        "command_id",
        "status",
        "completed_at",
        "error",
        "failure_code",
        "failure_stage",
        "failure_message_public",
    }
)
V85_TIMESTAMP_PATTERN = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z")


class ActionProcessEnvelope(NamedTuple):
    job_id: str
    process_id: str
    action_id: str
    user_id: str
    user_step_id: str | None
    claimed_user_message_id: str | None


class _Process(NamedTuple):
    process_id: str
    user_id: str
    status: str
    action_id: str
    suggestion_id: object
    terminal_event_id: object
    completed_at: object


class _Job(NamedTuple):
    job_id: object
    user_id: object
    job_type: object
    process_id: object
    status: object
    logical_key: object
    error_code: object
    completed_at: object


class _Payload(NamedTuple):
    job_id: object
    payload_json: object
    created_at: object


class _V85Event(NamedTuple):
    process_id: object
    event_id: object
    event_name: object
    payload_json: object
    created_at: object


def load_action_process_envelopes(
    connection: sqlite3.Connection,
) -> tuple[ActionProcessEnvelope, ...]:
    cutoff = _load_v82_completed_at(connection)
    processes = _load_action_processes(connection)
    jobs = _load_jobs(connection)
    payloads = _load_payloads(connection)
    v85_completed, v85_events_by_process = _load_v85_certification_state(connection)
    payloads_by_job: dict[object, list[_Payload]] = {}
    for stored_payload in payloads:
        payloads_by_job.setdefault(stored_payload.job_id, []).append(stored_payload)
    action_processes_by_job = _validate_inventory(processes, jobs, payloads_by_job)

    current: list[ActionProcessEnvelope] = []
    for stored_payload in payloads:
        job = jobs.get(stored_payload.job_id)
        requires_action_payload = job is not None and job.job_type == "execute_action"
        decoded = _decode_payload(
            stored_payload.payload_json, required=requires_action_payload
        )
        if isinstance(decoded, dict) and "continuation_ref" in decoded:
            candidate = _parse_current_payload(cast(dict[str, object], decoded))
            validated = _validate_current_envelope(
                stored_payload, candidate, jobs, action_processes_by_job
            )
            if validated.user_step_id is None:
                validated = _claim_certified_v85_message(
                    validated,
                    job,
                    action_processes_by_job.get(stored_payload.job_id),
                    v85_completed=v85_completed,
                    event_rows=v85_events_by_process.get(validated.process_id, ()),
                )
            current.append(validated)
            continue
        if not requires_action_payload:
            continue
        assert job is not None
        process = action_processes_by_job[job.job_id]
        if _is_pre_v82_terminal(stored_payload, job, process, cutoff):
            continue
        if not isinstance(decoded, dict):
            raise MigrationError("Action process contains malformed job payload JSON")
        raise MigrationError("Action job payload is missing continuation_ref")
    for job_id, process in action_processes_by_job.items():
        if payloads_by_job.get(job_id):
            continue
        job = jobs[job_id]
        envelope = ActionProcessEnvelope(
            job_id=_required_text(job.job_id, field="job_id"),
            process_id=process.process_id,
            action_id=process.action_id,
            user_id=process.user_id,
            user_step_id=None,
            claimed_user_message_id=None,
        )
        certified = _claim_certified_v85_message(
            envelope,
            job,
            process,
            v85_completed=v85_completed,
            event_rows=v85_events_by_process.get(process.process_id, ()),
        )
        if certified.claimed_user_message_id is None:
            raise MigrationError(
                f"Action job payload count is invalid: job_id={job_id} count=0"
            )
        current.append(certified)
    return tuple(current)


def _load_action_processes(
    connection: sqlite3.Connection,
) -> dict[str, _Process]:
    rows = connection.execute(
        """
        SELECT
            processes.process_id, processes.user_id, processes.status,
            processes.action_id, processes.suggestion_id,
            processes.terminal_event_id, processes.completed_at,
            actions.action_id, actions.user_id, actions.suggestion_id
        FROM processes
        LEFT JOIN agent_actions AS actions
          ON actions.action_id = processes.action_id
        WHERE processes.kind = 'action'
        ORDER BY processes.process_id
        """
    )
    processes: dict[str, _Process] = {}
    for row in rows:
        process_id = _required_text(row[0], field="process_id")
        user_id = _required_text(row[1], field="process_user_id")
        status = _required_text(row[2], field="process_status")
        action_id = _required_text(row[3], field="process_action_id")
        if (row[7], row[8], row[9]) != (action_id, user_id, row[4]):
            raise MigrationError(
                f"Action process ownership is inconsistent: process_id={process_id}"
            )
        processes[process_id] = _Process(
            process_id,
            user_id,
            status,
            action_id,
            row[4],
            row[5],
            row[6],
        )
    return processes


def _load_jobs(connection: sqlite3.Connection) -> dict[object, _Job]:
    query = (
        "SELECT job_id,user_id,job_type,process_id,status,logical_key,error_code,"
        "completed_at "
        "FROM jobs ORDER BY job_id"
    )
    return {row[0]: _Job(*row) for row in connection.execute(query)}


def _load_payloads(connection: sqlite3.Connection) -> tuple[_Payload, ...]:
    query = "SELECT job_id,payload_json,created_at FROM job_payloads ORDER BY rowid"
    return tuple(_Payload(*row) for row in connection.execute(query))


def _validate_inventory(
    processes: dict[str, _Process],
    jobs: dict[object, _Job],
    payloads_by_job: dict[object, list[_Payload]],
) -> dict[object, _Process]:
    action_jobs_by_process: dict[str, list[_Job]] = {}
    processes_by_job: dict[object, _Process] = {}
    for job in jobs.values():
        if job.job_type != "execute_action":
            continue
        job_id = _required_text(job.job_id, field="job_id")
        process_id = _required_text(job.process_id, field="job_process_id")
        process = processes.get(process_id)
        if (
            process is None
            or job.user_id != process.user_id
            or job.logical_key != process.action_id
        ):
            raise MigrationError(
                f"Action job ownership is inconsistent: job_id={job_id}"
            )
        payload_count = len(payloads_by_job.get(job.job_id, ()))
        if payload_count > 1:
            raise MigrationError(
                f"Action job payload count is invalid: job_id={job_id} count={payload_count}"
            )
        action_jobs_by_process.setdefault(process_id, []).append(job)
        processes_by_job[job.job_id] = process
    for process_id in processes:
        job_count = len(action_jobs_by_process.get(process_id, ()))
        if job_count != 1:
            raise MigrationError(
                "Action process job count is invalid: "
                f"process_id={process_id} count={job_count}"
            )
    return processes_by_job


def _parse_current_payload(payload: dict[str, object]) -> ActionProcessEnvelope:
    _require_exact_fields(payload, ACTION_PAYLOAD_FIELDS, label="Action job payload")
    raw_continuation = payload["continuation_ref"]
    if not isinstance(raw_continuation, dict):
        raise MigrationError("Action continuation_ref must be an object")
    continuation = cast(dict[str, object], raw_continuation)
    kind = _required_payload_text(continuation, "kind")
    user_step_id: str | None = None
    if kind == "user_step":
        _require_exact_fields(
            continuation,
            USER_STEP_CONTINUATION_FIELDS,
            label="Action user_step continuation_ref",
        )
        user_step_id = _required_payload_text(continuation, "user_step_id")
    elif kind == "tool_approval":
        _require_exact_fields(
            continuation,
            TOOL_APPROVAL_CONTINUATION_FIELDS,
            label="Action tool_approval continuation_ref",
        )
        _required_payload_text(continuation, "approval_session_id")
        _required_payload_text(continuation, "tool_request_id")
    else:
        raise MigrationError(f"Unsupported Action continuation_ref kind: {kind}")
    return ActionProcessEnvelope(
        job_id=_required_payload_text(payload, "job_id"),
        process_id=_required_payload_text(payload, "process_id"),
        action_id=_required_payload_text(payload, "action_id"),
        user_id=_required_payload_text(payload, "user_id"),
        user_step_id=user_step_id,
        claimed_user_message_id=None,
    )


def _validate_current_envelope(
    stored_payload: _Payload,
    payload: ActionProcessEnvelope,
    jobs: dict[object, _Job],
    processes_by_job: dict[object, _Process],
) -> ActionProcessEnvelope:
    job = jobs.get(stored_payload.job_id)
    process = processes_by_job.get(stored_payload.job_id)
    if (
        job is None
        or process is None
        or (payload.job_id, payload.process_id, payload.action_id, payload.user_id)
        != (job.job_id, process.process_id, process.action_id, process.user_id)
    ):
        identity = payload.user_step_id or payload.job_id
        raise MigrationError(f"Action process envelope is inconsistent: id={identity}")
    return payload


def _claim_certified_v85_message(
    envelope: ActionProcessEnvelope,
    job: _Job | None,
    process: _Process | None,
    *,
    v85_completed: bool,
    event_rows: Sequence[_V85Event],
) -> ActionProcessEnvelope:
    if job is None or process is None:
        raise MigrationError(
            f"Action process envelope is inconsistent: id={envelope.job_id}"
        )
    event_id = f"v85-legacy-goal-worker-internal:{process.process_id}"
    has_v85_marker = (
        job.error_code == V85_FAILURE_CODE
        or (
            isinstance(process.terminal_event_id, str)
            and process.terminal_event_id.startswith("v85-legacy-goal-worker-internal:")
        )
        or bool(event_rows)
    )
    if not has_v85_marker:
        return envelope
    if (
        job.status != "failed"
        or job.error_code != V85_FAILURE_CODE
        or process.status != "failed"
        or process.terminal_event_id != event_id
        or len(event_rows) != 1
        or event_rows[0].event_id != event_id
        or not v85_completed
    ):
        raise MigrationError(
            f"Action v85 lineage certification is inconsistent: job_id={envelope.job_id}"
        )
    event_row = event_rows[0]
    payload = _decode_payload(event_row.payload_json, required=True)
    if event_row.event_name != "stream_end" or not isinstance(payload, dict):
        raise MigrationError(
            f"Action v85 lineage certification is malformed: job_id={envelope.job_id}"
        )
    event = cast(dict[str, object], payload)
    expected_fields = V85_EVENT_FIELDS
    if process.suggestion_id is not None:
        expected_fields = expected_fields | {"suggestion_id"}
    command_id = _required_text(event.get("command_id"), field="v85_event_command_id")
    completed_at = _required_v85_timestamp(event_row.created_at)
    if (
        set(event) != expected_fields
        or event.get("kind") != "action"
        or event.get("process_id") != process.process_id
        or event.get("action_id") != process.action_id
        or (
            process.suggestion_id is not None
            and event.get("suggestion_id") != process.suggestion_id
        )
        or event.get("status") != "error"
        or event.get("completed_at") != completed_at
        or completed_at != process.completed_at
        or completed_at != job.completed_at
        or event.get("failure_code") != V85_FAILURE_CODE
        or event.get("failure_stage") != V85_FAILURE_STAGE
        or event.get("failure_message_public") != V85_FAILURE_MESSAGE
        or not _is_exact_v85_error(event.get("error"))
    ):
        raise MigrationError(
            f"Action v85 lineage certification is inconsistent: job_id={envelope.job_id}"
        )
    return envelope._replace(claimed_user_message_id=command_id)


def _is_exact_v85_error(value: object) -> bool:
    return (
        isinstance(value, dict)
        and set(value) == V85_ERROR_FIELDS
        and value.get("error_code") == V85_FAILURE_CODE
        and value.get("error_type") == "resume_error"
        and value.get("error_message") == V85_FAILURE_MESSAGE
        and value.get("severity") == "error"
    )


def _load_v85_certification_state(
    connection: sqlite3.Connection,
) -> tuple[bool, dict[object, list[_V85Event]]]:
    events_by_process: dict[object, list[_V85Event]] = {}
    rows = connection.execute(
        "SELECT process_id,event_id,event_name,payload_json,created_at "
        "FROM process_events "
        "WHERE event_id LIKE 'v85-legacy-goal-worker-internal:%' "
        "ORDER BY process_id,event_seq"
    )
    for row in rows:
        event = _V85Event(*row)
        events_by_process.setdefault(event.process_id, []).append(event)
    return _has_completed_v85_migration(connection), events_by_process


def _has_completed_v85_migration(connection: sqlite3.Connection) -> bool:
    row = connection.execute(
        """
        SELECT COUNT(*) FROM migration_journal
        WHERE component='local_runtime'
          AND migration_name=?
          AND from_version=84
          AND to_version=85
          AND status='completed'
          AND completed_at IS NOT NULL
          AND LENGTH(TRIM(completed_at)) > 0
        """,
        (V85_MIGRATION_NAME,),
    ).fetchone()
    return row is not None and row[0] == 1


def _load_v82_completed_at(connection: sqlite3.Connection) -> datetime:
    row = connection.execute(
        """
        SELECT completed_at FROM migration_journal
        WHERE component='local_runtime' AND to_version=82 AND status='completed'
        ORDER BY completed_at DESC LIMIT 1
        """
    ).fetchone()
    if row is None:
        raise MigrationError("Completed v82 migration is required")
    return _required_utc_timestamp(row[0], field="v82_completed_at")


def _required_v85_timestamp(value: object) -> str:
    text = _required_text(value, field="v85_event_completed_at")
    if V85_TIMESTAMP_PATTERN.fullmatch(text) is None:
        raise MigrationError(
            "Action v85 lineage certification has invalid completed_at"
        )
    _required_utc_timestamp(text, field="v85_event_completed_at")
    return text


def _is_pre_v82_terminal(
    payload: _Payload,
    job: _Job,
    process: _Process,
    cutoff: datetime,
) -> bool:
    return (
        _required_utc_timestamp(payload.created_at, field="payload_created_at") < cutoff
        and job.status in TERMINAL_JOB_STATUSES
        and process.status in TERMINAL_PROCESS_STATUSES
    )


def _decode_payload(payload_json: object, *, required: bool) -> object:
    if isinstance(payload_json, str):
        try:
            return json.loads(payload_json)
        except json.JSONDecodeError:
            pass
    if not required:
        return None
    raise MigrationError("Action process contains malformed job payload JSON")


def _require_exact_fields(
    payload: dict[str, object], expected: frozenset[str], *, label: str
) -> None:
    if set(payload) != expected:
        raise MigrationError(f"{label} has invalid fields")


def _required_payload_text(payload: dict[str, object], field: str) -> str:
    return _required_text(payload.get(field), field=field)


def _required_text(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise MigrationError(f"Action process inventory has invalid {field}")
    return value


def _required_utc_timestamp(value: object, *, field: str) -> datetime:
    text = _required_text(value, field=field)
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise MigrationError(f"Action process inventory has invalid {field}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise MigrationError(f"Action process inventory has invalid {field}")
    return parsed.astimezone(UTC)


__all__ = ["ActionProcessEnvelope", "load_action_process_envelopes"]
