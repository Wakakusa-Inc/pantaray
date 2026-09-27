from __future__ import annotations

import sqlite3

from pantaray_agents.local_runtime.storage.sqlite_vector import (
    load_sqlite_vector_extension,
)

from .constants import (
    BUSY_TIMEOUT_PRAGMA_TEMPLATE,
    FOREIGN_KEYS_ON_PRAGMA,
    JOURNAL_MODE_WAL_PRAGMA,
    SYNCHRONOUS_FULL_PRAGMA,
    WAL_AUTOCHECKPOINT_DISABLED_PRAGMA,
)


def configure_connection(connection: sqlite3.Connection, busy_timeout_ms: int) -> None:
    load_sqlite_vector_extension(connection)
    connection.execute(JOURNAL_MODE_WAL_PRAGMA)
    connection.execute(SYNCHRONOUS_FULL_PRAGMA)
    connection.execute(WAL_AUTOCHECKPOINT_DISABLED_PRAGMA)
    connection.execute(BUSY_TIMEOUT_PRAGMA_TEMPLATE.format(timeout_ms=busy_timeout_ms))
    connection.execute(FOREIGN_KEYS_ON_PRAGMA)


def ensure_meta_tables(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_versions (
            schema_version_id TEXT PRIMARY KEY,
            component TEXT NOT NULL,
            current_version INTEGER NOT NULL CHECK (current_version >= 0),
            applied_at TEXT NOT NULL,
            app_version TEXT NOT NULL,
            migration_name TEXT NOT NULL,
            checksum TEXT NOT NULL,
            UNIQUE(component)
        );
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS migration_journal (
            migration_run_id TEXT PRIMARY KEY,
            migration_name TEXT NOT NULL,
            component TEXT NOT NULL,
            from_version INTEGER NOT NULL CHECK (from_version >= 0),
            to_version INTEGER NOT NULL CHECK (to_version >= from_version),
            started_at TEXT NOT NULL,
            completed_at TEXT,
            status TEXT NOT NULL CHECK (status IN ('running', 'completed', 'failed')),
            app_version TEXT NOT NULL,
            checksum TEXT NOT NULL,
            error_message TEXT
        );
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS runtime_recovery_runs (
            recovery_run_id TEXT PRIMARY KEY,
            started_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
            status TEXT NOT NULL,
            note TEXT NOT NULL
        );
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS job_payloads (
            job_id TEXT PRIMARY KEY,
            payload_json TEXT NOT NULL CHECK (json_valid(payload_json)),
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
            FOREIGN KEY (job_id) REFERENCES jobs(job_id) ON DELETE CASCADE
        );
        """
    )


def column_exists(
    connection: sqlite3.Connection, *, table_name: str, column_name: str
) -> bool:
    rows = connection.execute(f"PRAGMA table_info({table_name})").fetchall()
    return any(str(row[1]) == column_name for row in rows)


def table_exists(connection: sqlite3.Connection, *, table_name: str) -> bool:
    row = connection.execute(
        """
        SELECT name
        FROM sqlite_master
        WHERE type = 'table' AND name = ?
        """,
        (table_name,),
    ).fetchone()
    return row is not None


def add_column_if_missing(
    connection: sqlite3.Connection, *, table_name: str, column_definition: str
) -> None:
    column_name = column_definition.split()[0]
    if column_exists(connection, table_name=table_name, column_name=column_name):
        return
    connection.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_definition}")
