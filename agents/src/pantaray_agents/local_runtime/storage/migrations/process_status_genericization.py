from __future__ import annotations

import sqlite3

from .action_status_alignment_fk import (
    drop_legacy_tables,
    rebuild_tables_with_legacy_foreign_keys,
)
from .connection import table_exists

LEGACY_PROCESSES_TABLE = "processes_legacy_v20"


def apply_process_status_genericization_migration(
    connection: sqlite3.Connection,
) -> None:
    if not table_exists(connection, table_name="processes"):
        return
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
        FROM processes_legacy_v20
        """
    )
    rebuild_tables_with_legacy_foreign_keys(
        connection,
        legacy_table_names=(LEGACY_PROCESSES_TABLE,),
    )
    drop_legacy_tables(connection, legacy_table_names=(LEGACY_PROCESSES_TABLE,))
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
