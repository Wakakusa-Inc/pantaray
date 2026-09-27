from __future__ import annotations

import sqlite3

from .connection import add_column_if_missing, table_exists


def apply_runtime_process_lock_ledger_migration(
    connection: sqlite3.Connection,
) -> None:
    if not table_exists(connection, table_name="runtime_lock_resources"):
        connection.execute(
            """
            CREATE TABLE runtime_lock_resources (
                resource_id TEXT PRIMARY KEY,
                lock_path TEXT NOT NULL,
                lock_id TEXT NOT NULL,
                owner_pid INTEGER NOT NULL CHECK (owner_pid > 0),
                status TEXT NOT NULL CHECK (
                    status IN ('active', 'cleaned', 'cleanup_failed', 'abandoned')
                ),
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                cleaned_at TEXT,
                cleanup_error TEXT,
                cleanup_attempts INTEGER NOT NULL DEFAULT 0 CHECK (cleanup_attempts >= 0)
            )
            """
        )
    if not table_exists(connection, table_name="runtime_lock_events"):
        connection.execute(
            """
            CREATE TABLE runtime_lock_events (
                event_id TEXT PRIMARY KEY,
                resource_id TEXT,
                event_type TEXT NOT NULL,
                message TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (resource_id) REFERENCES runtime_lock_resources(resource_id) ON DELETE SET NULL
            )
            """
        )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_runtime_lock_resources_status_created ON runtime_lock_resources(status, created_at ASC)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_runtime_lock_events_resource_created ON runtime_lock_events(resource_id, created_at ASC)"
    )


def apply_remove_socket_resource_scope_migration(
    connection: sqlite3.Connection,
) -> None:
    connection.execute(
        """
        UPDATE tool_runtime_resources
        SET
            status = 'abandoned',
            updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now'),
            cleanup_error = 'socket resources are outside the current local runtime transport scope',
            cleanup_attempts = CASE
                WHEN status IN ('active', 'cleanup_failed') THEN cleanup_attempts + 1
                ELSE cleanup_attempts
            END
        WHERE resource_kind = 'socket'
          AND status IN ('active', 'cleanup_failed')
        """
    )
    connection.execute(
        """
        CREATE TRIGGER IF NOT EXISTS reject_tool_runtime_resource_socket_insert
        BEFORE INSERT ON tool_runtime_resources
        FOR EACH ROW
        WHEN NEW.resource_kind = 'socket'
        BEGIN
            SELECT RAISE(ABORT, 'socket resources are outside the current local runtime transport scope');
        END;
        """
    )


def apply_workspace_lock_owner_token_migration(
    connection: sqlite3.Connection,
) -> None:
    add_column_if_missing(
        connection,
        table_name="tool_runtime_resources",
        column_definition="lock_id TEXT",
    )
    connection.execute(
        """
        CREATE TRIGGER IF NOT EXISTS reject_tool_runtime_resource_socket_update
        BEFORE UPDATE OF resource_kind ON tool_runtime_resources
        FOR EACH ROW
        WHEN NEW.resource_kind = 'socket'
        BEGIN
            SELECT RAISE(ABORT, 'socket resources are outside the current local runtime transport scope');
        END;
        """
    )
