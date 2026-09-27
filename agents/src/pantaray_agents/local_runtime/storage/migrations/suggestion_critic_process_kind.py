from __future__ import annotations

import sqlite3

from .connection import table_exists

LEGACY_PROCESSES_TABLE = "processes_legacy_v22"
LEGACY_PROCESS_EVENTS_TABLE = "process_events_legacy_v22"
LEGACY_JOBS_TABLE = "jobs_legacy_v22"
LEGACY_JOB_ATTEMPTS_TABLE = "job_attempts_legacy_v22"
LEGACY_JOB_PAYLOADS_TABLE = "job_payloads_legacy_v22"


def apply_suggestion_critic_process_kind_migration(
    connection: sqlite3.Connection,
) -> None:
    if not table_exists(connection, table_name="processes"):
        return
    _rename_existing_tables(connection)
    _create_processes_table(connection)
    _create_process_events_table(connection)
    _create_jobs_table(connection)
    _create_job_attempts_table(connection)
    _create_job_payloads_table(connection)
    _copy_legacy_rows(connection)
    _drop_legacy_tables(connection)
    _create_indexes(connection)


def _rename_existing_tables(connection: sqlite3.Connection) -> None:
    connection.execute(
        f"ALTER TABLE job_payloads RENAME TO {LEGACY_JOB_PAYLOADS_TABLE}"
    )
    connection.execute(
        f"ALTER TABLE job_attempts RENAME TO {LEGACY_JOB_ATTEMPTS_TABLE}"
    )
    connection.execute(f"ALTER TABLE jobs RENAME TO {LEGACY_JOBS_TABLE}")
    connection.execute(
        f"ALTER TABLE process_events RENAME TO {LEGACY_PROCESS_EVENTS_TABLE}"
    )
    connection.execute(f"ALTER TABLE processes RENAME TO {LEGACY_PROCESSES_TABLE}")


def _create_processes_table(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE processes (
            process_id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            kind TEXT NOT NULL CHECK (
                kind IN (
                    'suggestion',
                    'suggestion_critic',
                    'action',
                    'insight',
                    'fact',
                    'activity_description',
                    'activity_summary'
                )
            ),
            status TEXT NOT NULL CHECK (
                status IN (
                    'enqueued',
                    'running',
                    'paused',
                    'completed',
                    'failed',
                    'canceled',
                    'success',
                    'error',
                    'abandoned'
                )
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


def _create_process_events_table(connection: sqlite3.Connection) -> None:
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


def _create_jobs_table(connection: sqlite3.Connection) -> None:
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
            logical_key TEXT,
            FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
            FOREIGN KEY (process_id) REFERENCES processes(process_id) ON DELETE SET NULL
        )
        """
    )


def _create_job_attempts_table(connection: sqlite3.Connection) -> None:
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


def _create_job_payloads_table(connection: sqlite3.Connection) -> None:
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


def _copy_legacy_rows(connection: sqlite3.Connection) -> None:
    connection.execute(
        f"""
        INSERT INTO processes(
            process_id,
            user_id,
            kind,
            status,
            suggestion_id,
            action_id,
            started_at,
            updated_at,
            completed_at,
            heartbeat_at,
            terminal_event_id,
            acknowledged_at,
            current_job_id,
            next_event_seq
        )
        SELECT
            process_id,
            user_id,
            kind,
            status,
            suggestion_id,
            action_id,
            started_at,
            updated_at,
            completed_at,
            heartbeat_at,
            terminal_event_id,
            acknowledged_at,
            current_job_id,
            next_event_seq
        FROM {LEGACY_PROCESSES_TABLE}
        """
    )
    connection.execute(
        f"""
        INSERT INTO jobs(
            job_id,
            user_id,
            job_type,
            process_id,
            status,
            attempt,
            claimed_by,
            claimed_at,
            heartbeat_at,
            cancel_requested_at,
            timeout_at,
            next_retry_at,
            scheduled_at,
            started_at,
            completed_at,
            error_code,
            logical_key
        )
        SELECT
            job_id,
            user_id,
            job_type,
            process_id,
            status,
            attempt,
            claimed_by,
            claimed_at,
            heartbeat_at,
            cancel_requested_at,
            timeout_at,
            next_retry_at,
            scheduled_at,
            started_at,
            completed_at,
            error_code,
            logical_key
        FROM {LEGACY_JOBS_TABLE}
        """
    )
    connection.execute(
        f"""
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
        FROM {LEGACY_JOB_ATTEMPTS_TABLE}
        """
    )
    connection.execute(
        f"""
        INSERT INTO job_payloads(job_id, payload_json, created_at)
        SELECT job_id, payload_json, created_at
        FROM {LEGACY_JOB_PAYLOADS_TABLE}
        """
    )
    connection.execute(
        f"""
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
        FROM {LEGACY_PROCESS_EVENTS_TABLE}
        """
    )


def _drop_legacy_tables(connection: sqlite3.Connection) -> None:
    connection.execute(f"DROP TABLE {LEGACY_JOB_PAYLOADS_TABLE}")
    connection.execute(f"DROP TABLE {LEGACY_JOB_ATTEMPTS_TABLE}")
    connection.execute(f"DROP TABLE {LEGACY_JOBS_TABLE}")
    connection.execute(f"DROP TABLE {LEGACY_PROCESS_EVENTS_TABLE}")
    connection.execute(f"DROP TABLE {LEGACY_PROCESSES_TABLE}")


def _create_indexes(connection: sqlite3.Connection) -> None:
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
    connection.execute(
        "CREATE INDEX idx_process_events_process_created ON process_events(process_id, created_at ASC)"
    )
    connection.execute(
        "CREATE INDEX idx_process_events_name_created ON process_events(event_name, created_at DESC)"
    )
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
    connection.execute(
        "CREATE INDEX idx_jobs_type_logical_key ON jobs(job_type, logical_key)"
    )
    connection.execute(
        "CREATE INDEX idx_job_attempts_job ON job_attempts(job_id, attempt_number ASC)"
    )
