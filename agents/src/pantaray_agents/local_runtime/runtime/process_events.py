from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..storage.migrations import MigrationError
from ..storage.migrations.connection import configure_connection
from ..storage.transactions import immediate_transaction
from .job_types import ACTION_PROCESS_KIND, LOCAL_ACTION_JOB_TYPE
from .utc_timestamps import now_utc_iso

BUSY_TIMEOUT_PRAGMA_TEMPLATE = "PRAGMA busy_timeout = {timeout_ms};"
FOREIGN_KEYS_ON_PRAGMA = "PRAGMA foreign_keys = ON;"
PROCESS_STATUS_ENQUEUED = "enqueued"
PROCESS_STATUS_PROCESSING = "running"
PROCESS_STATUS_PAUSED = "paused"
PROCESS_STATUS_FAILED = "failed"
JOB_STATUS_PENDING = "queued"
JOB_STATUS_RUNNING = "running"
JOB_STATUS_PAUSED = "paused"
JOB_STATUS_COMPLETED = "completed"
JOB_STATUS_FAILED = "failed"
JOB_STATUS_CANCELED = "canceled"
TERMINAL_JOB_STATUSES = frozenset(
    {JOB_STATUS_COMPLETED, JOB_STATUS_FAILED, JOB_STATUS_CANCELED}
)


@dataclass(frozen=True)
class LocalProcessEventRecord:
    cursor: int
    event_id: str
    event_type: str
    payload: dict[str, Any]
    created_at: str


def _configure_connection(connection: sqlite3.Connection, busy_timeout_ms: int) -> None:
    connection.execute(BUSY_TIMEOUT_PRAGMA_TEMPLATE.format(timeout_ms=busy_timeout_ms))
    connection.execute(FOREIGN_KEYS_ON_PRAGMA)


def _require_positive_timeout(busy_timeout_ms: int) -> None:
    if busy_timeout_ms <= 0:
        raise MigrationError("LOCAL_DB_BUSY_TIMEOUT_MS must be a positive integer")


def append_process_event_in_connection(
    *,
    connection: sqlite3.Connection,
    process_id: str,
    event_name: str,
    payload: dict[str, object],
    created_at: str,
    event_id: str | None = None,
) -> str:
    if not process_id.strip():
        raise MigrationError("process_id must not be empty")
    if not event_name.strip():
        raise MigrationError("event_name must not be empty")

    resolved_event_id = event_id or str(uuid.uuid4())
    next_event_seq_row = connection.execute(
        "SELECT next_event_seq FROM processes WHERE process_id = ?",
        (process_id,),
    ).fetchone()
    if next_event_seq_row is None:
        raise MigrationError(f"process not found: {process_id}")
    next_event_seq = int(next_event_seq_row[0])
    connection.execute(
        """
        INSERT INTO process_events(
            process_id,
            event_seq,
            event_id,
            event_name,
            payload_json,
            chunk_index,
            created_at
        ) VALUES (?, ?, ?, ?, ?, NULL, ?)
        """,
        (
            process_id,
            next_event_seq,
            resolved_event_id,
            event_name,
            json.dumps(payload, ensure_ascii=False),
            created_at,
        ),
    )
    connection.execute(
        """
        UPDATE processes
        SET
            next_event_seq = next_event_seq + 1,
            updated_at = ?,
            terminal_event_id = CASE
                WHEN ? IN ('stream_end', 'process_timeout', 'process_canceled')
                    THEN ?
                ELSE terminal_event_id
            END
        WHERE process_id = ?
        """,
        (created_at, event_name, resolved_event_id, process_id),
    )
    return resolved_event_id


def append_local_process_event(
    *,
    db_path: Path,
    busy_timeout_ms: int,
    process_id: str,
    event_type: str,
    payload: dict[str, Any],
    event_id: str | None = None,
) -> str:
    _require_positive_timeout(busy_timeout_ms)
    if not process_id.strip():
        raise MigrationError("process_id must not be empty")
    if not event_type.strip():
        raise MigrationError("event_type must not be empty")

    created_at = now_utc_iso()
    with sqlite3.connect(db_path) as connection:
        _configure_connection(connection, busy_timeout_ms)
        with connection:
            return append_process_event_in_connection(
                connection=connection,
                process_id=process_id,
                event_name=event_type,
                payload=payload,
                created_at=created_at,
                event_id=event_id,
            )


def append_local_action_step_event(
    *,
    db_path: Path,
    busy_timeout_ms: int,
    process_id: str,
    payload: dict[str, object],
) -> str | None:
    _require_positive_timeout(busy_timeout_ms)
    if not process_id.strip():
        raise MigrationError("process_id must not be empty")
    created_at = now_utc_iso()
    with sqlite3.connect(db_path) as connection:
        _configure_connection(connection, busy_timeout_ms)
        with immediate_transaction(connection):
            process_row = connection.execute(
                "SELECT terminal_event_id FROM processes WHERE process_id = ?",
                (process_id,),
            ).fetchone()
            if process_row is None:
                raise MigrationError(f"process not found: {process_id}")
            if process_row[0] is not None:
                return None
            return append_process_event_in_connection(
                connection=connection,
                process_id=process_id,
                event_name="action_step",
                payload=payload,
                created_at=created_at,
            )


def update_local_process_status(
    *,
    db_path: Path,
    busy_timeout_ms: int,
    process_id: str,
    status: str,
) -> None:
    _require_positive_timeout(busy_timeout_ms)
    if not process_id.strip():
        raise MigrationError("process_id must not be empty")
    if not status.strip():
        raise MigrationError("status must not be empty")
    with sqlite3.connect(db_path) as connection:
        _configure_connection(connection, busy_timeout_ms)
        with connection:
            connection.execute(
                """
                UPDATE processes
                SET status = ?, updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
                WHERE process_id = ?
                """,
                (status, process_id),
            )


def update_local_job_status(
    *,
    db_path: Path,
    busy_timeout_ms: int,
    job_id: str,
    status: str,
) -> None:
    _require_positive_timeout(busy_timeout_ms)
    if not job_id.strip():
        raise MigrationError("job_id must not be empty")
    if not status.strip():
        raise MigrationError("status must not be empty")
    with sqlite3.connect(db_path) as connection:
        _configure_connection(connection, busy_timeout_ms)
        with connection:
            connection.execute(
                """
                UPDATE jobs
                SET
                    status = ?,
                    heartbeat_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now'),
                    completed_at = CASE
                        WHEN ? IN ('completed', 'failed', 'canceled')
                            THEN strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
                        ELSE completed_at
                    END
                WHERE job_id = ?
                """,
                (status, status, job_id),
            )


def mark_local_action_job_started(
    *,
    db_path: Path,
    busy_timeout_ms: int,
    job_id: str,
    process_id: str,
    payload: dict[str, Any],
) -> str:
    update_local_job_status(
        db_path=db_path,
        busy_timeout_ms=busy_timeout_ms,
        job_id=job_id,
        status=JOB_STATUS_RUNNING,
    )
    update_local_process_status(
        db_path=db_path,
        busy_timeout_ms=busy_timeout_ms,
        process_id=process_id,
        status=PROCESS_STATUS_PROCESSING,
    )
    return append_local_process_event(
        db_path=db_path,
        busy_timeout_ms=busy_timeout_ms,
        process_id=process_id,
        event_type="process_started",
        payload=payload,
    )


def mark_local_action_job_paused(
    *,
    db_path: Path,
    busy_timeout_ms: int,
    job_id: str,
    process_id: str,
    payload: dict[str, Any],
) -> str | None:
    """Park one running Action job, or report that a Stop fence outranks it."""

    _require_positive_timeout(busy_timeout_ms)
    if not job_id.strip():
        raise MigrationError("job_id must not be empty")
    if not process_id.strip():
        raise MigrationError("process_id must not be empty")
    _require_resumable_approval_blockers(payload)
    action_id = _require_pause_identity(payload, field_name="action_id")
    user_id = _require_pause_identity(payload, field_name="user_id")
    # Deferred: the snapshot writer appends through this module, so importing it
    # at module scope would be circular.
    from .action_approval_projection import (
        append_pending_approval_snapshot_in_connection,
    )

    paused_at = now_utc_iso()
    with sqlite3.connect(db_path) as connection:
        configure_connection(connection, busy_timeout_ms)
        with immediate_transaction(connection):
            if not _pause_action_job_in_connection(
                connection=connection,
                job_id=job_id,
                process_id=process_id,
                action_id=action_id,
                user_id=user_id,
                paused_at=paused_at,
            ):
                return None
            # The relay stops forwarding this process at the pause anchor, so
            # the snapshot has to reach the stream before it.
            append_pending_approval_snapshot_in_connection(
                connection,
                user_id=user_id,
                action_id=action_id,
                root_process_id=process_id,
                created_at=paused_at,
                root_pause_blockers=payload["approval_blockers"],
            )
            return append_process_event_in_connection(
                connection=connection,
                process_id=process_id,
                event_name="process_paused",
                payload=payload,
                created_at=paused_at,
            )


def _require_resumable_approval_blockers(payload: dict[str, Any]) -> None:
    blockers = payload.get("approval_blockers")
    if not isinstance(blockers, list) or not blockers:
        raise MigrationError("process pause requires approval_blockers")
    for blocker in blockers:
        if not isinstance(blocker, dict):
            raise MigrationError("approval blocker must be an object")
        for field_name in ("approval_session_id", "tool_request_id"):
            value = blocker.get(field_name)
            if not isinstance(value, str) or not value.strip():
                raise MigrationError(
                    f"approval blocker {field_name} must be a non-empty string"
                )


def _require_pause_identity(payload: dict[str, Any], *, field_name: str) -> str:
    value = payload.get(field_name)
    if not isinstance(value, str) or not value.strip():
        raise MigrationError(f"process pause {field_name} must be a non-empty string")
    return value


def _pause_action_job_in_connection(
    *,
    connection: sqlite3.Connection,
    job_id: str,
    process_id: str,
    action_id: str,
    user_id: str,
    paused_at: str,
) -> bool:
    row = connection.execute(
        """
        SELECT
            jobs.user_id AS job_user_id,
            jobs.job_type,
            jobs.status AS job_status,
            jobs.logical_key,
            processes.user_id AS process_user_id,
            processes.kind AS process_kind,
            processes.status AS process_status,
            processes.action_id,
            processes.current_job_id,
            jobs.cancel_requested_at
        FROM jobs
        JOIN processes ON processes.process_id = jobs.process_id
        WHERE jobs.job_id = ? AND jobs.process_id = ?
        """,
        (job_id, process_id),
    ).fetchone()
    if row is None:
        raise MigrationError("Action pause job/process binding was not found")
    if (
        str(row[0]) != user_id
        or str(row[0]) != str(row[4])
        or str(row[1]) != LOCAL_ACTION_JOB_TYPE
        or str(row[2]) != JOB_STATUS_RUNNING
        or str(row[3]) != action_id
        or str(row[5]) != ACTION_PROCESS_KIND
        or str(row[6]) != PROCESS_STATUS_PROCESSING
        or str(row[7]) != action_id
        or str(row[8]) != job_id
    ):
        raise MigrationError("Action pause job/process state is inconsistent")
    if row[9] is not None:
        # A Stop fence already decided this run. Parking it would strand the
        # cancel behind an approval nobody will answer, so the caller converges
        # on the cancel terminal that also settles this parent's children.
        return False

    job_cursor = connection.execute(
        """
        UPDATE jobs
        SET
            status = ?,
            claimed_by = NULL,
            claimed_at = NULL,
            heartbeat_at = ?,
            completed_at = NULL,
            error_code = NULL
        WHERE job_id = ? AND process_id = ? AND status = ?
        """,
        (JOB_STATUS_PAUSED, paused_at, job_id, process_id, JOB_STATUS_RUNNING),
    )
    process_cursor = connection.execute(
        """
        UPDATE processes
        SET
            status = ?,
            completed_at = NULL,
            current_job_id = NULL,
            updated_at = ?,
            heartbeat_at = ?
        WHERE process_id = ? AND status = ? AND current_job_id = ?
        """,
        (
            PROCESS_STATUS_PAUSED,
            paused_at,
            paused_at,
            process_id,
            PROCESS_STATUS_PROCESSING,
            job_id,
        ),
    )
    attempt_cursor = connection.execute(
        """
        UPDATE job_attempts
        SET status = 'completed', completed_at = ?, error_code = NULL,
            error_message = NULL
        WHERE job_id = ? AND status = 'running'
        """,
        (paused_at, job_id),
    )
    if (
        int(job_cursor.rowcount) != 1
        or int(process_cursor.rowcount) != 1
        or int(attempt_cursor.rowcount) != 1
    ):
        raise MigrationError(
            "Action pause transition did not close one running attempt"
        )
    return True


def read_local_process_events_after(
    *,
    db_path: Path,
    busy_timeout_ms: int,
    process_id: str,
    after_cursor: int,
    limit: int,
) -> list[LocalProcessEventRecord]:
    _require_positive_timeout(busy_timeout_ms)
    if limit <= 0:
        raise MigrationError("limit must be positive")
    with sqlite3.connect(db_path) as connection:
        _configure_connection(connection, busy_timeout_ms)
        rows = connection.execute(
            """
            SELECT
                process_event_rowid,
                event_id,
                event_name,
                payload_json,
                created_at
            FROM process_events
            WHERE process_id = ? AND process_event_rowid > ?
            ORDER BY process_event_rowid ASC
            LIMIT ?
            """,
            (process_id, after_cursor, limit),
        ).fetchall()
    events: list[LocalProcessEventRecord] = []
    for row in rows:
        payload_obj = json.loads(str(row[3]))
        if not isinstance(payload_obj, dict):
            raise MigrationError(
                f"process event payload must be object: process_id={process_id}"
            )
        events.append(
            LocalProcessEventRecord(
                cursor=int(row[0]),
                event_id=str(row[1]),
                event_type=str(row[2]),
                payload=payload_obj,
                created_at=str(row[4]),
            )
        )
    return events


def resolve_local_process_event_cursor(
    *,
    db_path: Path,
    busy_timeout_ms: int,
    process_id: str,
    event_id: str,
) -> int | None:
    _require_positive_timeout(busy_timeout_ms)
    normalized_event_id = event_id.strip()
    if not process_id.strip():
        raise MigrationError("process_id must not be empty")
    if not normalized_event_id:
        raise MigrationError("event_id must not be empty")
    with sqlite3.connect(db_path) as connection:
        _configure_connection(connection, busy_timeout_ms)
        row = connection.execute(
            """
            SELECT process_event_rowid
            FROM process_events
            WHERE process_id = ? AND event_id = ?
            """,
            (process_id, normalized_event_id),
        ).fetchone()
    if row is None:
        return None
    return int(row[0])


__all__ = [
    "LocalProcessEventRecord",
    "PROCESS_STATUS_ENQUEUED",
    "PROCESS_STATUS_FAILED",
    "PROCESS_STATUS_PROCESSING",
    "PROCESS_STATUS_PAUSED",
    "JOB_STATUS_PAUSED",
    "append_process_event_in_connection",
    "append_local_action_step_event",
    "append_local_process_event",
    "mark_local_action_job_paused",
    "mark_local_action_job_started",
    "read_local_process_events_after",
    "resolve_local_process_event_cursor",
    "update_local_job_status",
    "update_local_process_status",
]
