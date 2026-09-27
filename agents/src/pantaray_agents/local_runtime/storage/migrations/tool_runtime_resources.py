from __future__ import annotations

import sqlite3

from .connection import add_column_if_missing, table_exists


def apply_tool_runtime_resource_migration(connection: sqlite3.Connection) -> None:
    if not table_exists(connection, table_name="tool_runtime_resources"):
        connection.execute(
            """
            CREATE TABLE tool_runtime_resources (
                resource_id TEXT PRIMARY KEY,
                execution_session_id TEXT NOT NULL,
                tool_invocation_id TEXT,
                action_id TEXT,
                resource_kind TEXT NOT NULL CHECK (
                    resource_kind IN ('process_group', 'temp_file', 'temp_dir', 'lock')
                ),
                status TEXT NOT NULL CHECK (
                    status IN ('active', 'cleaned', 'cleanup_failed', 'abandoned')
                ),
                pid INTEGER,
                pgid INTEGER,
                process_start_signature TEXT,
                resource_path TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                cleaned_at TEXT,
                cleanup_error TEXT,
                cleanup_attempts INTEGER NOT NULL DEFAULT 0 CHECK (cleanup_attempts >= 0),
                FOREIGN KEY (execution_session_id) REFERENCES execution_sessions(execution_session_id) ON DELETE CASCADE,
                FOREIGN KEY (tool_invocation_id) REFERENCES tool_invocations(invocation_id) ON DELETE SET NULL
            )
            """
        )
    add_column_if_missing(
        connection,
        table_name="tool_runtime_resources",
        column_definition="cleanup_attempts INTEGER NOT NULL DEFAULT 0",
    )
    add_column_if_missing(
        connection,
        table_name="tool_runtime_resources",
        column_definition="process_start_signature TEXT",
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_tool_runtime_resources_status_created ON tool_runtime_resources(status, created_at ASC)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_tool_runtime_resources_invocation_status ON tool_runtime_resources(tool_invocation_id, status, created_at ASC)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_tool_runtime_resources_action_status ON tool_runtime_resources(action_id, status, created_at ASC)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_tool_redactions_output ON tool_redactions(output_id)"
    )


def apply_tool_runtime_resource_events_migration(
    connection: sqlite3.Connection,
) -> None:
    if not table_exists(connection, table_name="tool_runtime_resource_events"):
        connection.execute(
            """
            CREATE TABLE tool_runtime_resource_events (
                event_id TEXT PRIMARY KEY,
                resource_id TEXT,
                tool_invocation_id TEXT,
                action_id TEXT,
                event_type TEXT NOT NULL,
                message TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (resource_id) REFERENCES tool_runtime_resources(resource_id) ON DELETE SET NULL,
                FOREIGN KEY (tool_invocation_id) REFERENCES tool_invocations(invocation_id) ON DELETE SET NULL
            )
            """
        )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_tool_runtime_resource_events_invocation_created ON tool_runtime_resource_events(tool_invocation_id, created_at ASC)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_tool_runtime_resource_events_resource_created ON tool_runtime_resource_events(resource_id, created_at ASC)"
    )
