from __future__ import annotations

import sqlite3
from collections.abc import Callable

from .action_history_schema import (
    create_agent_actions_table,
    create_agent_suggestions_table,
)
from .action_status_alignment_fk import (
    drop_legacy_tables,
    drop_rebuild_temp_tables,
    rebuild_tables_with_legacy_foreign_keys,
)
from .action_status_alignment_normalize import (
    decode_json_object,
    json_dumps_compact,
    normalize_action_status_row,
    normalize_action_terminal_row,
    normalize_job_row,
    normalize_payload_status,
    normalize_process_row,
)
from .connection import table_exists
from .public_event_projection import create_public_history_table

LEGACY_PROCESSES_TABLE = "processes_legacy_v16"
LEGACY_PROCESS_EVENTS_TABLE = "process_events_legacy_v16"
LEGACY_JOBS_TABLE = "jobs_legacy_v16"
LEGACY_JOB_ATTEMPTS_TABLE = "job_attempts_legacy_v16"
LEGACY_JOB_PAYLOADS_TABLE = "job_payloads_legacy_v16"
LEGACY_SUGGESTIONS_TABLE = "agent_suggestions_legacy_v16"
LEGACY_ACTIONS_TABLE = "agent_actions_legacy_v16"
LEGACY_HISTORY_TABLE = "agent_suggestion_history_legacy_v16"


def apply_action_status_alignment_migration(connection: sqlite3.Connection) -> None:
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA defer_foreign_keys = ON;")
    _recreate_processes_table(connection)
    _recreate_process_events_table(connection)
    _recreate_jobs_table(connection)
    _recreate_job_attempts_table(connection)
    _recreate_job_payloads_table(connection)
    _recreate_agent_suggestions_table(connection)
    _recreate_agent_actions_table(connection)
    _recreate_public_history_table(connection)
    rebuild_tables_with_legacy_foreign_keys(
        connection,
        legacy_table_names=(
            LEGACY_SUGGESTIONS_TABLE,
            LEGACY_ACTIONS_TABLE,
            LEGACY_HISTORY_TABLE,
        ),
        skip_tables=(
            "agent_suggestions",
            "agent_actions",
            "agent_suggestion_history",
        ),
    )
    _normalize_internal_process_events(connection)
    _normalize_public_process_events(connection)
    drop_rebuild_temp_tables(connection)
    _drop_legacy_action_status_tables(connection)


def _recreate_processes_table(connection: sqlite3.Connection) -> None:
    if not table_exists(connection, table_name="processes"):
        return
    _drop_table_if_exists(connection, LEGACY_PROCESSES_TABLE)
    connection.execute(f"ALTER TABLE processes RENAME TO {LEGACY_PROCESSES_TABLE}")
    connection.execute(
        """
        CREATE TABLE processes (
            process_id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            kind TEXT NOT NULL CHECK (
                kind IN (
                    'suggestion',
                    'action',
                    'insight',
                    'fact',
                    'activity_description',
                    'activity_summary'
                )
            ),
            status TEXT NOT NULL CHECK (
                status IN ('enqueued', 'running', 'paused', 'completed', 'failed', 'canceled')
            ),
            suggestion_id TEXT,
            action_id TEXT,
            started_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            completed_at TEXT,
            heartbeat_at TEXT NOT NULL,
            terminal_event_id TEXT,
            acknowledged_at TEXT,
            current_job_id TEXT,
            next_event_seq INTEGER NOT NULL CHECK (next_event_seq >= 1),
            FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
        )
        """
    )
    _copy_rows_with_transform(
        connection,
        source_table=LEGACY_PROCESSES_TABLE,
        target_table="processes",
        transform=normalize_process_row,
    )
    connection.execute(f"DROP TABLE {LEGACY_PROCESSES_TABLE}")
    connection.execute(
        "CREATE INDEX idx_processes_user_updated ON processes(user_id, updated_at DESC)"
    )
    connection.execute(
        "CREATE INDEX idx_processes_kind_status ON processes(kind, status)"
    )
    connection.execute(
        """
        CREATE UNIQUE INDEX idx_processes_terminal_event_id
        ON processes(terminal_event_id) WHERE terminal_event_id IS NOT NULL
        """
    )


def _recreate_jobs_table(connection: sqlite3.Connection) -> None:
    if not table_exists(connection, table_name="jobs"):
        return
    _drop_table_if_exists(connection, LEGACY_JOBS_TABLE)
    connection.execute(f"ALTER TABLE jobs RENAME TO {LEGACY_JOBS_TABLE}")
    connection.execute(
        """
        CREATE TABLE jobs (
            job_id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            job_type TEXT NOT NULL,
            process_id TEXT,
            status TEXT NOT NULL CHECK (
                status IN (
                    'queued',
                    'running',
                    'paused',
                    'retryable_error',
                    'blocked',
                    'completed',
                    'failed',
                    'abandoned',
                    'canceled'
                )
            ),
            attempt INTEGER NOT NULL DEFAULT 0 CHECK (attempt >= 0),
            claimed_by TEXT,
            claimed_at TEXT,
            heartbeat_at TEXT,
            cancel_requested_at TEXT,
            timeout_at TEXT,
            next_retry_at TEXT,
            scheduled_at TEXT NOT NULL,
            started_at TEXT,
            completed_at TEXT,
            error_code TEXT,
            FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
            FOREIGN KEY (process_id) REFERENCES processes(process_id) ON DELETE SET NULL
        )
        """
    )
    _copy_rows_with_transform(
        connection,
        source_table=LEGACY_JOBS_TABLE,
        target_table="jobs",
        transform=normalize_job_row,
    )
    connection.execute(f"DROP TABLE {LEGACY_JOBS_TABLE}")
    connection.execute(
        "CREATE INDEX idx_jobs_status_schedule ON jobs(status, scheduled_at ASC)"
    )
    connection.execute("CREATE INDEX idx_jobs_process_id ON jobs(process_id)")
    connection.execute(
        """
        CREATE INDEX idx_jobs_retry
        ON jobs(status, next_retry_at ASC) WHERE status = 'retryable_error'
        """
    )


def _recreate_process_events_table(connection: sqlite3.Connection) -> None:
    if not table_exists(connection, table_name="process_events"):
        return
    _drop_table_if_exists(connection, LEGACY_PROCESS_EVENTS_TABLE)
    connection.execute(
        f"ALTER TABLE process_events RENAME TO {LEGACY_PROCESS_EVENTS_TABLE}"
    )
    connection.execute(
        """
        CREATE TABLE process_events (
            process_event_rowid INTEGER PRIMARY KEY AUTOINCREMENT,
            process_id TEXT NOT NULL,
            event_seq INTEGER NOT NULL CHECK (event_seq >= 1),
            event_id TEXT NOT NULL,
            event_name TEXT NOT NULL,
            payload_json TEXT NOT NULL CHECK (json_valid(payload_json)),
            chunk_index INTEGER,
            created_at TEXT NOT NULL,
            FOREIGN KEY (process_id) REFERENCES processes(process_id) ON DELETE CASCADE,
            UNIQUE (process_id, event_seq),
            UNIQUE (process_id, event_id)
        )
        """
    )
    connection.execute(
        """
        INSERT INTO process_events(
            process_event_rowid,
            process_id,
            event_seq,
            event_id,
            event_name,
            payload_json,
            chunk_index,
            created_at
        )
        SELECT
            process_event_rowid,
            process_id,
            event_seq,
            event_id,
            event_name,
            payload_json,
            chunk_index,
            created_at
        FROM """
        + LEGACY_PROCESS_EVENTS_TABLE
    )
    connection.execute(f"DROP TABLE {LEGACY_PROCESS_EVENTS_TABLE}")
    connection.execute(
        "CREATE INDEX idx_process_events_process_created ON process_events(process_id, created_at ASC)"
    )
    connection.execute(
        "CREATE INDEX idx_process_events_name_created ON process_events(event_name, created_at DESC)"
    )


def _recreate_job_attempts_table(connection: sqlite3.Connection) -> None:
    if not table_exists(connection, table_name="job_attempts"):
        return
    _drop_table_if_exists(connection, LEGACY_JOB_ATTEMPTS_TABLE)
    connection.execute(
        f"ALTER TABLE job_attempts RENAME TO {LEGACY_JOB_ATTEMPTS_TABLE}"
    )
    connection.execute(
        """
        CREATE TABLE job_attempts (
            attempt_id TEXT PRIMARY KEY,
            job_id TEXT NOT NULL,
            attempt_number INTEGER NOT NULL CHECK (attempt_number >= 1),
            started_at TEXT NOT NULL,
            completed_at TEXT,
            status TEXT NOT NULL CHECK (status IN ('running', 'completed', 'failed', 'canceled')),
            error_code TEXT,
            error_message TEXT,
            FOREIGN KEY (job_id) REFERENCES jobs(job_id) ON DELETE CASCADE,
            UNIQUE (job_id, attempt_number)
        )
        """
    )
    connection.execute(
        """
        INSERT INTO job_attempts(
            attempt_id,
            job_id,
            attempt_number,
            started_at,
            completed_at,
            status,
            error_code,
            error_message
        )
        SELECT
            attempt_id,
            job_id,
            attempt_number,
            started_at,
            completed_at,
            status,
            error_code,
            error_message
        FROM """
        + LEGACY_JOB_ATTEMPTS_TABLE
    )
    connection.execute(f"DROP TABLE {LEGACY_JOB_ATTEMPTS_TABLE}")
    connection.execute(
        "CREATE INDEX idx_job_attempts_job ON job_attempts(job_id, attempt_number ASC)"
    )


def _recreate_job_payloads_table(connection: sqlite3.Connection) -> None:
    if not table_exists(connection, table_name="job_payloads"):
        return
    _drop_table_if_exists(connection, LEGACY_JOB_PAYLOADS_TABLE)
    connection.execute(
        f"ALTER TABLE job_payloads RENAME TO {LEGACY_JOB_PAYLOADS_TABLE}"
    )
    connection.execute(
        """
        CREATE TABLE job_payloads (
            job_id TEXT PRIMARY KEY,
            payload_json TEXT NOT NULL CHECK (json_valid(payload_json)),
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
            FOREIGN KEY (job_id) REFERENCES jobs(job_id) ON DELETE CASCADE
        )
        """
    )
    connection.execute(
        """
        INSERT INTO job_payloads(job_id, payload_json, created_at)
        SELECT job_id, payload_json, created_at
        FROM """
        + LEGACY_JOB_PAYLOADS_TABLE
    )
    connection.execute(f"DROP TABLE {LEGACY_JOB_PAYLOADS_TABLE}")


def _recreate_agent_suggestions_table(connection: sqlite3.Connection) -> None:
    if not table_exists(connection, table_name="agent_suggestions"):
        return
    _drop_table_if_exists(connection, LEGACY_SUGGESTIONS_TABLE)
    connection.execute(
        f"ALTER TABLE agent_suggestions RENAME TO {LEGACY_SUGGESTIONS_TABLE}"
    )
    create_agent_suggestions_table(connection)
    _copy_rows_with_transform(
        connection,
        source_table=LEGACY_SUGGESTIONS_TABLE,
        target_table="agent_suggestions",
        transform=normalize_action_status_row,
    )


def _recreate_agent_actions_table(connection: sqlite3.Connection) -> None:
    if not table_exists(connection, table_name="agent_actions"):
        return
    _drop_table_if_exists(connection, LEGACY_ACTIONS_TABLE)
    connection.execute(f"ALTER TABLE agent_actions RENAME TO {LEGACY_ACTIONS_TABLE}")
    create_agent_actions_table(connection)
    _copy_rows_with_transform(
        connection,
        source_table=LEGACY_ACTIONS_TABLE,
        target_table="agent_actions",
        transform=normalize_action_terminal_row,
    )


def _recreate_public_history_table(connection: sqlite3.Connection) -> None:
    if not table_exists(connection, table_name="agent_suggestion_history"):
        return
    _drop_table_if_exists(connection, LEGACY_HISTORY_TABLE)
    connection.execute(
        f"ALTER TABLE agent_suggestion_history RENAME TO {LEGACY_HISTORY_TABLE}"
    )
    create_public_history_table(connection)
    _copy_rows_with_transform(
        connection,
        source_table=LEGACY_HISTORY_TABLE,
        target_table="agent_suggestion_history",
        transform=normalize_action_status_row,
    )


def _normalize_internal_process_events(connection: sqlite3.Connection) -> None:
    if not table_exists(connection, table_name="process_events"):
        return
    rows = connection.execute(
        """
        SELECT process_event_rowid, payload_json
        FROM process_events
        WHERE event_name = 'stream_end'
        """
    ).fetchall()
    for row in rows:
        payload = decode_json_object(row["payload_json"])
        updated_payload = normalize_payload_status(payload)
        connection.execute(
            "UPDATE process_events SET payload_json = ? WHERE process_event_rowid = ?",
            (json_dumps_compact(updated_payload), int(row["process_event_rowid"])),
        )


def _normalize_public_process_events(connection: sqlite3.Connection) -> None:
    if not table_exists(connection, table_name="agent_process_events"):
        return
    rows = connection.execute(
        """
        SELECT event_id, payload
        FROM agent_process_events
        WHERE event_name = 'process_completed'
        """
    ).fetchall()
    for row in rows:
        payload = decode_json_object(row["payload"])
        data = payload.get("data")
        if (
            isinstance(data, dict)
            and str(data.get("kind") or "").strip().lower() == "action"
        ):
            normalized = normalize_payload_status(payload)
            connection.execute(
                "UPDATE agent_process_events SET payload = ? WHERE event_id = ?",
                (json_dumps_compact(normalized), str(row["event_id"])),
            )


def _drop_legacy_action_status_tables(connection: sqlite3.Connection) -> None:
    drop_legacy_tables(
        connection,
        legacy_table_names=(
            LEGACY_HISTORY_TABLE,
            LEGACY_ACTIONS_TABLE,
            LEGACY_SUGGESTIONS_TABLE,
        ),
    )


def _drop_table_if_exists(connection: sqlite3.Connection, table_name: str) -> None:
    if table_exists(connection, table_name=table_name):
        connection.execute(f"DROP TABLE {table_name}")


def _copy_rows_with_transform(
    connection: sqlite3.Connection,
    *,
    source_table: str,
    target_table: str,
    transform: Callable[[dict[str, object]], dict[str, object]],
) -> None:
    columns = _table_columns(connection, table_name=target_table)
    rows = connection.execute(f"SELECT * FROM {source_table}").fetchall()
    placeholders = ", ".join("?" for _ in columns)
    insert_sql = (
        f"INSERT INTO {target_table} ({', '.join(columns)}) VALUES ({placeholders})"
    )
    for row in rows:
        payload = transform({column: row[column] for column in columns})
        connection.execute(insert_sql, [payload[column] for column in columns])


def _table_columns(connection: sqlite3.Connection, *, table_name: str) -> list[str]:
    rows = connection.execute(f"PRAGMA table_info({table_name})").fetchall()
    return [str(row[1]) for row in rows]
