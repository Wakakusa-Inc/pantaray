from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import NamedTuple

from ..storage.migrations import MigrationError
from ..tooling.models import StoredToolRuntimeResourceEvent
from ..tooling.resources.resource_db_support import (
    build_tool_runtime_resource_event,
)
from .action_legacy_shared_temp_resource_authority import (
    LegacyActionSharedTempResourceAuthority,
    list_legacy_action_shared_temp_resource_authorities_in_connection,
)


class LegacyActionEvidence(NamedTuple):
    action_id: str
    user_id: str
    suggestion_id: str | None
    status: str
    final_output: str
    error: str | None
    created_at: str
    updated_at: str


class LegacyProcessEvidence(NamedTuple):
    process_id: str
    user_id: str
    kind: str
    status: str
    suggestion_id: str | None
    action_id: str | None
    started_at: str
    updated_at: str
    completed_at: str | None
    heartbeat_at: str
    terminal_event_id: str | None
    acknowledged_at: str | None
    current_job_id: str | None
    next_event_seq: int


class LegacyJobEvidence(NamedTuple):
    job_id: str
    user_id: str
    job_type: str
    process_id: str | None
    status: str
    attempt: int
    claimed_by: str | None
    claimed_at: str | None
    heartbeat_at: str | None
    cancel_requested_at: str | None
    timeout_at: str | None
    next_retry_at: str | None
    scheduled_at: str
    started_at: str | None
    completed_at: str | None
    error_code: str | None
    logical_key: str | None


class LegacyJobPayloadEvidence(NamedTuple):
    job_id: str
    raw_json: str
    created_at: str


class LegacyJobAttemptEvidence(NamedTuple):
    attempt_id: str
    job_id: str
    attempt_number: int
    started_at: str
    completed_at: str | None
    status: str
    error_code: str | None
    error_message: str | None


class LegacyProcessEventEvidence(NamedTuple):
    rowid: int
    process_id: str
    event_seq: int
    event_id: str
    event_name: str
    raw_payload_json: str
    chunk_index: int | None
    created_at: str


class LegacyPublicEventEvidence(NamedTuple):
    event_id: str
    suggestion_id: str | None
    user_id: str
    action_id: str
    sequence: int
    event_name: str
    raw_payload_json: str
    created_at: str


class LegacyActionJobPurgeEvidence(NamedTuple):
    job: LegacyJobEvidence
    payload: LegacyJobPayloadEvidence
    attempts: tuple[LegacyJobAttemptEvidence, ...]


class LegacyActionProcessPurgeEvidence(NamedTuple):
    process: LegacyProcessEvidence
    jobs: tuple[LegacyActionJobPurgeEvidence, ...]
    events: tuple[LegacyProcessEventEvidence, ...]


class LegacyActionSharedTempRuntimePurgeAuthority(NamedTuple):
    resource_authority: LegacyActionSharedTempResourceAuthority
    action: LegacyActionEvidence
    processes: tuple[LegacyActionProcessPurgeEvidence, ...]
    resource_events: tuple[StoredToolRuntimeResourceEvent, ...]
    action_public_events: tuple[LegacyPublicEventEvidence, ...]


def list_legacy_action_shared_temp_runtime_purge_authorities_in_connection(
    *, connection: sqlite3.Connection, resolved_db_path: Path
) -> tuple[LegacyActionSharedTempRuntimePurgeAuthority, ...]:
    resources = list_legacy_action_shared_temp_resource_authorities_in_connection(
        connection=connection, resolved_db_path=resolved_db_path
    )
    return tuple(_load_authority(connection, row) for row in resources)


def _load_authority(
    connection: sqlite3.Connection,
    resource_authority: LegacyActionSharedTempResourceAuthority,
) -> LegacyActionSharedTempRuntimePurgeAuthority:
    core = resource_authority.core
    row = connection.execute(
        """SELECT action_id,user_id,suggestion_id,status,final_output,error,
                  created_at,updated_at FROM agent_actions WHERE action_id=?""",
        (core.action_id,),
    ).fetchone()
    if row is None:
        raise MigrationError("legacy Action purge evidence is incomplete")
    action = LegacyActionEvidence._make(row)
    if action.user_id != core.user_id:
        raise MigrationError("legacy Action purge owner is inconsistent")
    return LegacyActionSharedTempRuntimePurgeAuthority(
        resource_authority,
        action,
        _load_processes(connection, action=action),
        _load_resource_events(connection, resource_authority=resource_authority),
        _load_public_events(connection, action=action),
    )


def _load_processes(
    connection: sqlite3.Connection, *, action: LegacyActionEvidence
) -> tuple[LegacyActionProcessPurgeEvidence, ...]:
    direct_rows = connection.execute(
        f"SELECT {_PROCESS_COLUMNS} FROM processes WHERE action_id=? ORDER BY process_id",
        (action.action_id,),
    ).fetchall()
    direct_ids = tuple(str(row["process_id"]) for row in direct_rows)
    conditions = [
        "jobs.logical_key=?",
        "json_extract(payloads.payload_json,'$.action_id')=?",
    ]
    parameters: list[object] = [action.action_id, action.action_id]
    if direct_ids:
        conditions.append(f"jobs.process_id IN ({_marks(direct_ids)})")
        parameters.extend(direct_ids)
    current_job_ids = tuple(
        str(row["current_job_id"])
        for row in direct_rows
        if row["current_job_id"] is not None
    )
    if current_job_ids:
        conditions.append(f"jobs.job_id IN ({_marks(current_job_ids)})")
        parameters.extend(current_job_ids)
    seed_job_rows = connection.execute(
        f"""SELECT {_JOB_COLUMNS} FROM jobs
            LEFT JOIN job_payloads AS payloads ON payloads.job_id=jobs.job_id
            WHERE {" OR ".join(conditions)} ORDER BY jobs.job_id""",
        tuple(parameters),
    ).fetchall()
    process_ids = set(direct_ids)
    process_ids.update(
        str(row["process_id"]) for row in seed_job_rows if row["process_id"] is not None
    )
    if process_ids:
        identities = tuple(sorted(process_ids))
        process_rows = connection.execute(
            f"SELECT {_PROCESS_COLUMNS} FROM processes WHERE process_id IN ({_marks(identities)}) ORDER BY process_id",
            identities,
        ).fetchall()
        child_job_rows = connection.execute(
            f"SELECT {_JOB_COLUMNS} FROM jobs WHERE process_id IN ({_marks(identities)}) ORDER BY job_id",
            identities,
        ).fetchall()
    else:
        process_rows = child_job_rows = []
    jobs = {
        str(row["job_id"]): LegacyJobEvidence._make(row)
        for row in (*seed_job_rows, *child_job_rows)
    }
    processes = tuple(LegacyProcessEvidence._make(row) for row in process_rows)
    process_by_id = {row.process_id: row for row in processes}
    if any(
        row.user_id != action.user_id
        or row.action_id != action.action_id
        or row.suggestion_id != action.suggestion_id
        for row in processes
    ):
        raise MigrationError("legacy Action process ownership is inconsistent")
    if any(
        row.process_id not in process_by_id or row.user_id != action.user_id
        for row in jobs.values()
    ) or any(
        process.current_job_id is not None
        and (
            process.current_job_id not in jobs
            or jobs[process.current_job_id].process_id != process.process_id
        )
        for process in processes
    ):
        raise MigrationError("legacy Action job ownership is inconsistent")
    payloads = _load_payloads(connection, action=action, jobs=jobs)
    attempts = _load_attempts(connection, tuple(jobs))
    events = _load_process_events(connection, tuple(process_by_id))
    return tuple(
        LegacyActionProcessPurgeEvidence(
            process,
            tuple(
                LegacyActionJobPurgeEvidence(
                    job, payloads[job.job_id], attempts[job.job_id]
                )
                for job in sorted(jobs.values(), key=lambda item: item.job_id)
                if job.process_id == process.process_id
            ),
            events[process.process_id],
        )
        for process in processes
    )


def _load_payloads(
    connection: sqlite3.Connection,
    *,
    action: LegacyActionEvidence,
    jobs: dict[str, LegacyJobEvidence],
) -> dict[str, LegacyJobPayloadEvidence]:
    if not jobs:
        return {}
    job_ids = tuple(jobs)
    rows = connection.execute(
        f"""SELECT job_id,payload_json,created_at FROM job_payloads
            WHERE job_id IN ({_marks(job_ids)}) ORDER BY job_id""",
        job_ids,
    ).fetchall()
    payloads = {str(row["job_id"]): LegacyJobPayloadEvidence._make(row) for row in rows}
    for job in jobs.values():
        payload = payloads.get(job.job_id)
        if payload is None:
            raise MigrationError("legacy Action job payload is missing")
        try:
            decoded = json.loads(payload.raw_json)
        except ValueError as exc:
            raise MigrationError("legacy Action job payload is invalid") from exc
        if not isinstance(decoded, dict) or any(
            decoded.get(field) != expected
            for field, expected in (
                ("job_id", job.job_id),
                ("process_id", job.process_id),
                ("action_id", action.action_id),
                ("user_id", action.user_id),
            )
        ):
            raise MigrationError("legacy Action job payload ownership is inconsistent")
        if (
            "suggestion_id" in decoded
            and decoded["suggestion_id"] != action.suggestion_id
        ):
            raise MigrationError("legacy Action job payload Suggestion is inconsistent")
    return payloads


def _load_attempts(
    connection: sqlite3.Connection, job_ids: tuple[str, ...]
) -> dict[str, tuple[LegacyJobAttemptEvidence, ...]]:
    grouped: dict[str, list[LegacyJobAttemptEvidence]] = {
        job_id: [] for job_id in job_ids
    }
    if job_ids:
        rows = connection.execute(
            f"""SELECT {_ATTEMPT_COLUMNS} FROM job_attempts
                WHERE job_id IN ({_marks(job_ids)}) ORDER BY job_id,attempt_number""",
            job_ids,
        )
        for row in rows:
            grouped[str(row["job_id"])].append(LegacyJobAttemptEvidence._make(row))
    return {key: tuple(value) for key, value in grouped.items()}


def _load_process_events(
    connection: sqlite3.Connection, process_ids: tuple[str, ...]
) -> dict[str, tuple[LegacyProcessEventEvidence, ...]]:
    grouped: dict[str, list[LegacyProcessEventEvidence]] = {
        process_id: [] for process_id in process_ids
    }
    if process_ids:
        rows = connection.execute(
            f"""SELECT {_PROCESS_EVENT_COLUMNS} FROM process_events
                WHERE process_id IN ({_marks(process_ids)}) ORDER BY process_id,event_seq""",
            process_ids,
        )
        for row in rows:
            grouped[str(row["process_id"])].append(
                LegacyProcessEventEvidence._make(row)
            )
    return {key: tuple(value) for key, value in grouped.items()}


def _load_resource_events(
    connection: sqlite3.Connection,
    *,
    resource_authority: LegacyActionSharedTempResourceAuthority,
) -> tuple[StoredToolRuntimeResourceEvent, ...]:
    action_id = resource_authority.core.action_id
    resource_ids = tuple(row.resource_id for row in resource_authority.resources)
    invocation_ids = tuple(row.invocation_id for row in resource_authority.invocations)
    clauses = ["action_id=?"]
    parameters: list[object] = [action_id]
    for column, values in (
        ("resource_id", resource_ids),
        ("tool_invocation_id", invocation_ids),
    ):
        if values:
            clauses.append(f"{column} IN ({_marks(values)})")
            parameters.extend(values)
    rows = connection.execute(
        f"""SELECT event_id,resource_id,tool_invocation_id,action_id,event_type,
                   message,created_at FROM tool_runtime_resource_events
            WHERE {" OR ".join(clauses)} ORDER BY event_id""",
        tuple(parameters),
    ).fetchall()
    events = tuple(build_tool_runtime_resource_event(row) for row in rows)
    if any(
        row.action_id != action_id
        or (row.resource_id is not None and row.resource_id not in resource_ids)
        or (
            row.tool_invocation_id is not None
            and row.tool_invocation_id not in invocation_ids
        )
        for row in events
    ):
        raise MigrationError("legacy Action resource event ownership is inconsistent")
    return events


def _load_public_events(
    connection: sqlite3.Connection, *, action: LegacyActionEvidence
) -> tuple[LegacyPublicEventEvidence, ...]:
    rows = connection.execute(
        f"""SELECT {_PUBLIC_EVENT_COLUMNS} FROM agent_process_events
            WHERE action_id=? ORDER BY sequence,event_id""",
        (action.action_id,),
    ).fetchall()
    events = tuple(LegacyPublicEventEvidence._make(row) for row in rows)
    if any(
        row.user_id != action.user_id
        or row.action_id != action.action_id
        or row.suggestion_id not in {None, action.suggestion_id}
        for row in events
    ):
        raise MigrationError("legacy Action public event ownership is inconsistent")
    return events


def _marks(values: tuple[object, ...]) -> str:
    return ",".join("?" for _ in values)


_PROCESS_COLUMNS = """process_id,user_id,kind,status,suggestion_id,action_id,started_at,updated_at,completed_at,heartbeat_at,terminal_event_id,acknowledged_at,current_job_id,next_event_seq"""
_JOB_COLUMNS = """jobs.job_id,jobs.user_id,jobs.job_type,jobs.process_id,jobs.status,jobs.attempt,jobs.claimed_by,jobs.claimed_at,jobs.heartbeat_at,jobs.cancel_requested_at,jobs.timeout_at,jobs.next_retry_at,jobs.scheduled_at,jobs.started_at,jobs.completed_at,jobs.error_code,jobs.logical_key"""
_ATTEMPT_COLUMNS = """attempt_id,job_id,attempt_number,started_at,completed_at,status,error_code,error_message"""
_PROCESS_EVENT_COLUMNS = """process_event_rowid,process_id,event_seq,event_id,event_name,payload_json,chunk_index,created_at"""
_PUBLIC_EVENT_COLUMNS = """event_id,suggestion_id,user_id,action_id,sequence,event_name,payload,created_at"""
