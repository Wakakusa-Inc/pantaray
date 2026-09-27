from __future__ import annotations

import sqlite3
from typing import NotRequired, TypedDict

from pantaray_agents.local_runtime.storage.migrations import MigrationError
from pantaray_agents.local_runtime.storage.migrations.connection import (
    configure_connection,
)
from pantaray_agents.local_runtime.storage.users import ensure_user_row

from .job_envelope import (
    LocalJobEnvelopeIntegrityError,
    load_local_job_envelope,
    require_valid_local_job_envelope,
)
from .job_status import (
    ACTIVE_DEDUPE_JOB_STATUSES,
    JOB_STATUS_QUEUED,
    JOB_STATUS_RUNNING,
    PROCESS_STATUS_ENQUEUED,
)
from .job_types import ACTION_SUBAGENT_PROCESS_KIND, PROCESS_KIND_BY_JOB_TYPE


class LocalJobEnqueueRequest(TypedDict):
    job_id: str
    user_id: str
    job_type: str
    process_id: str
    process_kind: str
    process_status: str
    scheduled_at: str
    logical_key: str
    payload_json: str
    process_started_at: str
    process_updated_at: str
    process_heartbeat_at: str
    process_next_event_seq: int
    process_suggestion_id: NotRequired[str | None]
    process_action_id: NotRequired[str | None]
    process_parent_process_id: NotRequired[str | None]


class LocalJobEnqueueResult(TypedDict):
    job_id: str
    process_id: str
    inserted_new: bool


def enqueue_local_job(
    *,
    connection: sqlite3.Connection,
    request: LocalJobEnqueueRequest,
) -> LocalJobEnqueueResult:
    _validate_enqueue_request(request)
    existing_by_id = _find_job_by_id(connection=connection, job_id=request["job_id"])
    if existing_by_id is not None:
        if existing_by_id != _job_identity(request):
            raise MigrationError(
                f"job_id already exists with different identity: {request['job_id']}"
            )
        return {
            "job_id": request["job_id"],
            "process_id": request["process_id"],
            "inserted_new": False,
        }
    existing_job = find_active_local_job(
        connection=connection,
        job_type=request["job_type"],
        logical_key=request["logical_key"],
    )
    if existing_job is not None:
        if existing_job["user_id"] != request["user_id"]:
            raise LocalJobEnvelopeIntegrityError(
                "active local job owner does not match enqueue request"
            )
        return {
            "job_id": existing_job["job_id"],
            "process_id": existing_job["process_id"],
            "inserted_new": False,
        }

    ensure_user_row(
        connection, user_id=request["user_id"], timestamp=request["scheduled_at"]
    )
    _insert_process_row(connection=connection, request=request)
    connection.execute(
        """
        INSERT INTO jobs(
            job_id,
            user_id,
            job_type,
            process_id,
            status,
            scheduled_at,
            logical_key
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            request["job_id"],
            request["user_id"],
            request["job_type"],
            request["process_id"],
            JOB_STATUS_QUEUED,
            request["scheduled_at"],
            request["logical_key"],
        ),
    )
    connection.execute(
        "INSERT INTO job_payloads(job_id, payload_json) VALUES (?, ?)",
        (request["job_id"], request["payload_json"]),
    )
    return {
        "job_id": request["job_id"],
        "process_id": request["process_id"],
        "inserted_new": True,
    }


def enqueue_local_job_with_connection(
    *,
    db_path: str,
    busy_timeout_ms: int,
    request: LocalJobEnqueueRequest,
) -> LocalJobEnqueueResult:
    if busy_timeout_ms <= 0:
        raise MigrationError("LOCAL_DB_BUSY_TIMEOUT_MS must be a positive integer")
    with sqlite3.connect(db_path) as connection:
        configure_connection(connection, busy_timeout_ms)
        connection.execute("BEGIN IMMEDIATE")
        try:
            result = enqueue_local_job(connection=connection, request=request)
            connection.commit()
            return result
        except Exception:
            connection.rollback()
            raise


class ActiveJobRef(TypedDict):
    job_id: str
    process_id: str
    user_id: str
    payload_json: str


class JobIdentity(TypedDict):
    user_id: str
    job_type: str
    process_id: str
    logical_key: str
    payload_json: str
    process_parent_process_id: str | None


def _job_identity(request: LocalJobEnqueueRequest) -> JobIdentity:
    return {
        "user_id": request["user_id"],
        "job_type": request["job_type"],
        "process_id": request["process_id"],
        "logical_key": request["logical_key"],
        "payload_json": request["payload_json"],
        "process_parent_process_id": request.get("process_parent_process_id"),
    }


def _find_job_by_id(
    *,
    connection: sqlite3.Connection,
    job_id: str,
) -> JobIdentity | None:
    envelope = load_local_job_envelope(connection=connection, job_id=job_id)
    if envelope is None:
        return None
    require_valid_local_job_envelope(envelope)
    if (
        envelope.process_id is None
        or envelope.logical_key is None
        or envelope.payload_json is None
    ):
        raise LocalJobEnvelopeIntegrityError(
            "existing local job identity is incomplete"
        )
    parent_process_id: str | None = None
    if envelope.process_kind == ACTION_SUBAGENT_PROCESS_KIND:
        process_row = connection.execute(
            "SELECT parent_process_id FROM processes WHERE process_id = ?",
            (envelope.process_id,),
        ).fetchone()
        if process_row is None:
            raise LocalJobEnvelopeIntegrityError("existing local job has no process")
        if process_row[0] is not None:
            parent_process_id = str(process_row[0])
    return {
        "user_id": envelope.job_user_id,
        "job_type": envelope.job_type,
        "process_id": envelope.process_id,
        "logical_key": envelope.logical_key,
        "payload_json": envelope.payload_json,
        "process_parent_process_id": parent_process_id,
    }


def find_active_local_job(
    *,
    connection: sqlite3.Connection,
    job_type: str,
    logical_key: str,
) -> ActiveJobRef | None:
    row = connection.execute(
        f"""
        SELECT job_id
        FROM jobs
        WHERE job_type = ?
          AND logical_key = ?
          AND status IN ({",".join("?" for _ in ACTIVE_DEDUPE_JOB_STATUSES)})
        ORDER BY scheduled_at ASC
        LIMIT 1
        """,
        (job_type, logical_key, *ACTIVE_DEDUPE_JOB_STATUSES),
    ).fetchone()
    if row is None:
        return None
    envelope = load_local_job_envelope(connection=connection, job_id=str(row[0]))
    if envelope is None:
        raise LocalJobEnvelopeIntegrityError(
            "active local job disappeared during lookup"
        )
    require_valid_local_job_envelope(
        envelope,
        expected_job_type=job_type,
        expected_process_status=(
            JOB_STATUS_RUNNING
            if envelope.job_status == JOB_STATUS_RUNNING
            else PROCESS_STATUS_ENQUEUED
        ),
    )
    if envelope.process_id is None or envelope.payload_json is None:
        raise LocalJobEnvelopeIntegrityError("active local job identity is incomplete")
    return {
        "job_id": envelope.job_id,
        "process_id": envelope.process_id,
        "user_id": envelope.job_user_id,
        "payload_json": envelope.payload_json,
    }


def _insert_process_row(
    *,
    connection: sqlite3.Connection,
    request: LocalJobEnqueueRequest,
) -> None:
    try:
        parent_process_id = request.get("process_parent_process_id")
        if parent_process_id is not None:
            connection.execute(
                """
                INSERT INTO processes(
                    process_id,user_id,kind,status,suggestion_id,action_id,
                    started_at,updated_at,heartbeat_at,next_event_seq,
                    parent_process_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    request["process_id"],
                    request["user_id"],
                    request["process_kind"],
                    request["process_status"],
                    request.get("process_suggestion_id"),
                    request.get("process_action_id"),
                    request["process_started_at"],
                    request["process_updated_at"],
                    request["process_heartbeat_at"],
                    request["process_next_event_seq"],
                    parent_process_id,
                ),
            )
            return
        connection.execute(
            """
            INSERT INTO processes(
                process_id,
                user_id,
                kind,
                status,
                suggestion_id,
                action_id,
                started_at,
                updated_at,
                heartbeat_at,
                next_event_seq
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                request["process_id"],
                request["user_id"],
                request["process_kind"],
                request["process_status"],
                request.get("process_suggestion_id"),
                request.get("process_action_id"),
                request["process_started_at"],
                request["process_updated_at"],
                request["process_heartbeat_at"],
                request["process_next_event_seq"],
            ),
        )
    except sqlite3.IntegrityError as exc:
        existing_row = connection.execute(
            "SELECT 1 FROM processes WHERE process_id = ?",
            (request["process_id"],),
        ).fetchone()
        if existing_row is not None:
            raise MigrationError(
                f"process_id already exists and cannot be reused: {request['process_id']}"
            ) from exc
        raise MigrationError(f"failed to insert process row: {exc}") from exc


def _validate_enqueue_request(request: LocalJobEnqueueRequest) -> None:
    for key in (
        "job_id",
        "user_id",
        "job_type",
        "process_id",
        "process_kind",
        "process_status",
        "scheduled_at",
        "logical_key",
        "payload_json",
        "process_started_at",
        "process_updated_at",
        "process_heartbeat_at",
    ):
        if not str(request[key]).strip():
            raise MigrationError(f"{key} must not be empty")
    if request["process_next_event_seq"] < 1:
        raise MigrationError("process_next_event_seq must be >= 1")
    expected_process_kind = PROCESS_KIND_BY_JOB_TYPE.get(request["job_type"])
    if expected_process_kind is None:
        raise MigrationError(f"unsupported local job_type: {request['job_type']}")
    if request["process_kind"] != expected_process_kind:
        raise MigrationError("local job_type and process_kind do not match")
    parent_process_id = request.get("process_parent_process_id")
    if request["process_kind"] == ACTION_SUBAGENT_PROCESS_KIND:
        if parent_process_id is None or not parent_process_id.strip():
            raise MigrationError(
                "process_parent_process_id must identify the Action parent"
            )
    elif parent_process_id is not None:
        raise MigrationError(
            "process_parent_process_id is only valid for Action subagents"
        )
