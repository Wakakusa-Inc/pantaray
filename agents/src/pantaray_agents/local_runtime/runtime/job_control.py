from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from pantaray_agents.local_runtime.storage.migrations import MigrationError
from pantaray_agents.local_runtime.storage.migrations.connection import (
    configure_connection,
)

from .job_claim import PROCESS_RUNTIME_STATUS
from .job_envelope import (
    LocalJobEnvelope,
    LocalJobEnvelopeIntegrityError,
    load_local_job_envelope,
    require_valid_local_job_envelope,
)
from .process_events import append_process_event_in_connection

LOCAL_JOB_DISPATCH_FAILED_ERROR_CODE = "LOCAL_JOB_DISPATCH_FAILED"
LOCAL_JOB_OPERATIONAL_RETRY_DELAY_SECONDS = 5


# Not frozen: re-raising through a context manager assigns ``__traceback__``.
#
# Not an ``Exception``: by the time this is raised the requeue is already
# committed, and this is only the signal carrying it back to the executor. Every
# layer it travels through -- the agents above all, which turn any ``Exception``
# raised around an LLM call into an error response their caller then persists --
# would otherwise convert a job that is queued to run again into a terminal
# failure the user sees. ``BaseException`` keeps those handlers from seeing it,
# the way ``asyncio.CancelledError`` keeps them from seeing a cancel.
@dataclass(eq=False)
class DeferredLocalJob(BaseException):
    job_id: str
    scheduled_at: str

    def __str__(self) -> str:
        return (
            f"local job deferred: job_id={self.job_id} scheduled_at={self.scheduled_at}"
        )


@dataclass(frozen=True, slots=True)
class LocalJobDeferEvent:
    event_name: str
    payload: dict[str, object]
    created_at: str


def defer_local_job(
    *,
    db_path: str,
    busy_timeout_ms: int,
    job_id: str,
    process_id: str,
    scheduled_at: str,
    process_pending_status: str,
    process_event: LocalJobDeferEvent | None = None,
    attempt_error_code: str | None = None,
) -> None:
    if busy_timeout_ms <= 0:
        raise MigrationError("LOCAL_DB_BUSY_TIMEOUT_MS must be a positive integer")
    if not job_id.strip():
        raise MigrationError("job_id must not be empty")
    if not process_id.strip():
        raise MigrationError("process_id must not be empty")
    if not scheduled_at.strip():
        raise MigrationError("scheduled_at must not be empty")
    if attempt_error_code is not None and not attempt_error_code.strip():
        raise MigrationError("attempt_error_code must not be empty")

    with sqlite3.connect(db_path) as connection:
        configure_connection(connection, busy_timeout_ms)
        with connection:
            envelope = _require_running_job_envelope(
                connection=connection,
                job_id=job_id,
                process_id=process_id,
            )
            job_cursor = connection.execute(
                """
                UPDATE jobs
                SET
                    status = 'queued',
                    scheduled_at = ?,
                    claimed_by = NULL,
                    claimed_at = NULL,
                    heartbeat_at = NULL
                WHERE job_id = ? AND user_id = ? AND job_type = ? AND process_id = ?
                  AND status = 'running'
                """,
                (
                    scheduled_at,
                    job_id,
                    envelope.job_user_id,
                    envelope.job_type,
                    process_id,
                ),
            )
            if int(job_cursor.rowcount) != 1:
                raise LocalJobEnvelopeIntegrityError("local job changed during defer")
            process_cursor = connection.execute(
                """
                UPDATE processes
                SET
                    status = ?,
                    current_job_id = NULL,
                    updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now'),
                    heartbeat_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
                WHERE process_id = ? AND user_id = ? AND kind = ?
                  AND current_job_id = ? AND status = 'running'
                """,
                (
                    process_pending_status,
                    process_id,
                    envelope.job_user_id,
                    envelope.process_kind,
                    job_id,
                ),
            )
            if int(process_cursor.rowcount) != 1:
                raise LocalJobEnvelopeIntegrityError(
                    "local job process changed during defer"
                )
            connection.execute(
                """
                UPDATE job_attempts
                SET
                    status = ?,
                    completed_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now'),
                    error_code = ?
                WHERE job_id = ? AND status = 'running'
                """,
                (
                    "failed" if attempt_error_code is not None else "completed",
                    attempt_error_code,
                    job_id,
                ),
            )
            if process_event is not None:
                append_process_event_in_connection(
                    connection=connection,
                    process_id=process_id,
                    event_name=process_event.event_name,
                    payload=process_event.payload,
                    created_at=process_event.created_at,
                )


def requeue_claimed_local_job_after_dispatch_failure(
    *,
    db_path: str,
    busy_timeout_ms: int,
    job_id: str,
    process_id: str,
    process_pending_status: PROCESS_RUNTIME_STATUS,
) -> None:
    """Return a claimed but unstarted job to its pending state atomically."""
    if busy_timeout_ms <= 0:
        raise MigrationError("LOCAL_DB_BUSY_TIMEOUT_MS must be a positive integer")
    if not job_id.strip():
        raise MigrationError("job_id must not be empty")
    if not process_id.strip():
        raise MigrationError("process_id must not be empty")

    with sqlite3.connect(db_path) as connection:
        configure_connection(connection, busy_timeout_ms)
        with connection:
            envelope = _require_running_job_envelope(
                connection=connection,
                job_id=job_id,
                process_id=process_id,
            )
            job_cursor = connection.execute(
                """
                UPDATE jobs
                SET
                    status = 'queued',
                    scheduled_at = strftime(
                        '%Y-%m-%dT%H:%M:%fZ', 'now', ?
                    ),
                    claimed_by = NULL,
                    claimed_at = NULL,
                    heartbeat_at = NULL,
                    error_code = NULL
                WHERE job_id = ? AND user_id = ? AND job_type = ?
                  AND process_id = ? AND status = 'running'
                """,
                (
                    f"+{LOCAL_JOB_OPERATIONAL_RETRY_DELAY_SECONDS} seconds",
                    job_id,
                    envelope.job_user_id,
                    envelope.job_type,
                    process_id,
                ),
            )
            if int(job_cursor.rowcount) != 1:
                raise MigrationError(
                    "claimed job changed before dispatch failure recovery"
                )
            process_cursor = connection.execute(
                """
                UPDATE processes
                SET
                    status = ?,
                    current_job_id = NULL,
                    updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now'),
                    heartbeat_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
                WHERE process_id = ? AND user_id = ? AND kind = ?
                  AND current_job_id = ? AND status = 'running'
                """,
                (
                    process_pending_status,
                    process_id,
                    envelope.job_user_id,
                    envelope.process_kind,
                    job_id,
                ),
            )
            if int(process_cursor.rowcount) != 1:
                raise MigrationError(
                    "claimed process changed before dispatch failure recovery"
                )
            attempt_cursor = connection.execute(
                """
                UPDATE job_attempts
                SET
                    status = 'failed',
                    completed_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now'),
                    error_code = ?,
                    error_message = 'Executor rejected the claimed job before start.'
                WHERE job_id = ? AND status = 'running'
                """,
                (LOCAL_JOB_DISPATCH_FAILED_ERROR_CODE, job_id),
            )
            if int(attempt_cursor.rowcount) != 1:
                raise MigrationError(
                    "running attempt changed before dispatch failure recovery"
                )


def _require_running_job_envelope(
    *,
    connection: sqlite3.Connection,
    job_id: str,
    process_id: str,
) -> LocalJobEnvelope:
    envelope = load_local_job_envelope(connection=connection, job_id=job_id)
    if envelope is None:
        raise LocalJobEnvelopeIntegrityError("local job does not exist")
    require_valid_local_job_envelope(
        envelope,
        expected_process_status="running",
    )
    if envelope.process_id != process_id:
        raise LocalJobEnvelopeIntegrityError(
            "local job process does not match its transition"
        )
    return envelope


__all__ = [
    "DeferredLocalJob",
    "LocalJobDeferEvent",
    "LOCAL_JOB_DISPATCH_FAILED_ERROR_CODE",
    "LOCAL_JOB_OPERATIONAL_RETRY_DELAY_SECONDS",
    "defer_local_job",
    "requeue_claimed_local_job_after_dispatch_failure",
]
