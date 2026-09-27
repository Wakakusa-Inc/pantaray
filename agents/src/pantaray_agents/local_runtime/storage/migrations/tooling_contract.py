from __future__ import annotations

import sqlite3

from .connection import add_column_if_missing, column_exists, table_exists
from .constants import (
    EMPTY_ALLOWED_CAPABILITIES_JSON,
    TOOL_DEFINITION_EMPTY_CAPABILITIES_JSON,
    TOOL_DEFINITION_EMPTY_GUIDE_JSON,
)


def apply_tooling_contract_migration(connection: sqlite3.Connection) -> None:
    _migrate_workspaces(connection)
    _migrate_execution_sessions(connection)
    _migrate_approval_preferences(connection)
    _migrate_capability_grants(connection)
    _migrate_approval_sessions(connection)
    _migrate_tool_definitions(connection)
    _migrate_tool_invocations(connection)
    _migrate_tool_outputs(connection)
    _migrate_tool_redactions(connection)


def _migrate_workspaces(connection: sqlite3.Connection) -> None:
    connection.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_workspaces_user_path ON workspaces(user_id, normalized_path)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_workspaces_root_id ON workspaces(root_id)"
    )


def _migrate_execution_sessions(connection: sqlite3.Connection) -> None:
    has_legacy_scratch_root = column_exists(
        connection,
        table_name="execution_sessions",
        column_name="scratch_root_path",
    )
    has_legacy_env_root = column_exists(
        connection,
        table_name="execution_sessions",
        column_name="env_root_path",
    )
    add_column_if_missing(
        connection,
        table_name="execution_sessions",
        column_definition="action_temp_dir TEXT",
    )
    add_column_if_missing(
        connection,
        table_name="execution_sessions",
        column_definition="app_runtime_python TEXT",
    )
    if has_legacy_scratch_root:
        connection.execute(
            """
            UPDATE execution_sessions
            SET action_temp_dir = COALESCE(action_temp_dir, scratch_root_path)
            WHERE action_temp_dir IS NULL AND scratch_root_path IS NOT NULL
            """
        )
    if has_legacy_env_root:
        connection.execute(
            """
            UPDATE execution_sessions
            SET app_runtime_python = COALESCE(app_runtime_python, env_root_path)
            WHERE app_runtime_python IS NULL AND env_root_path IS NOT NULL
            """
        )
    connection.execute(
        """
        UPDATE execution_sessions
        SET action_temp_dir = COALESCE(action_temp_dir, cwd_path)
        WHERE action_temp_dir IS NULL
        """
    )
    connection.execute(
        """
        UPDATE execution_sessions
        SET capability_snapshot_json = COALESCE(capability_snapshot_json, ?)
        WHERE capability_snapshot_json IS NULL
        """,
        (EMPTY_ALLOWED_CAPABILITIES_JSON,),
    )
    if column_exists(
        connection, table_name="execution_sessions", column_name="created_at"
    ):
        connection.execute(
            """
            UPDATE execution_sessions
            SET started_at = COALESCE(started_at, created_at)
            WHERE started_at IS NULL
            """
        )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_execution_sessions_action_started ON execution_sessions(action_id, started_at ASC)"
    )


def _migrate_capability_grants(connection: sqlite3.Connection) -> None:
    add_column_if_missing(
        connection,
        table_name="capability_grants",
        column_definition="capability_grant_id TEXT",
    )
    add_column_if_missing(
        connection,
        table_name="capability_grants",
        column_definition="capability_name TEXT",
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_capability_grants_user_capability ON capability_grants(user_id, capability, granted_at DESC)"
    )
    connection.execute(
        """
        UPDATE capability_grants
        SET
            capability_grant_id = COALESCE(capability_grant_id, grant_id),
            capability_name = COALESCE(capability_name, capability)
        WHERE
            capability_grant_id IS NULL
            OR capability_name IS NULL
        """
    )
    _rebuild_capability_grants_for_global_approval(connection)


def _rebuild_capability_grants_for_global_approval(
    connection: sqlite3.Connection,
) -> None:
    connection.execute("DROP TABLE IF EXISTS capability_grants__rebuild")
    connection.execute(
        """
        CREATE TABLE capability_grants__rebuild (
            grant_id TEXT PRIMARY KEY,
            capability_grant_id TEXT,
            user_id TEXT NOT NULL,
            preference_id TEXT,
            capability TEXT NOT NULL,
            capability_name TEXT,
            scope_type TEXT NOT NULL CHECK (scope_type = 'global'),
            scope_ref TEXT,
            grant_source TEXT NOT NULL CHECK (grant_source IN ('settings', 'prompt')),
            granted_at TEXT NOT NULL,
            granted_by TEXT NOT NULL CHECK (granted_by = 'user'),
            revoked_at TEXT,
            revocation_reason TEXT,
            FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
            FOREIGN KEY (preference_id)
                REFERENCES approval_preferences(preference_id) ON DELETE SET NULL,
            CHECK (scope_ref IS NULL)
        )
        """
    )
    connection.execute("DROP TABLE capability_grants")
    connection.execute(
        "ALTER TABLE capability_grants__rebuild RENAME TO capability_grants"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_capability_grants_user_capability ON capability_grants(user_id, capability, granted_at DESC)"
    )


def _migrate_approval_sessions(connection: sqlite3.Connection) -> None:
    has_legacy_consumed_at = column_exists(
        connection,
        table_name="approval_sessions",
        column_name="consumed_at",
    )
    add_column_if_missing(
        connection,
        table_name="approval_sessions",
        column_definition="tool_request_id TEXT",
    )
    add_column_if_missing(
        connection,
        table_name="approval_sessions",
        column_definition="claimed_at TEXT",
    )
    if has_legacy_consumed_at:
        connection.execute(
            """
            UPDATE approval_sessions
            SET claimed_at = COALESCE(claimed_at, consumed_at)
            WHERE consumed_at IS NOT NULL
            """
        )
    should_rebuild = has_legacy_consumed_at or not _approval_sessions_is_canonical(
        connection
    )
    if should_rebuild:
        _rebuild_approval_sessions_for_request_owned_approval(connection)
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_approval_sessions_action_status ON approval_sessions(action_id, status, requested_at DESC)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_approval_sessions_tool_invocation_status ON approval_sessions(tool_invocation_id, status, requested_at DESC)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_approval_sessions_user_tool_request_status ON approval_sessions(user_id, tool_request_id, status, requested_at DESC)"
    )


def _approval_sessions_is_canonical(
    connection: sqlite3.Connection,
) -> bool:
    table_info = connection.execute("PRAGMA table_info(approval_sessions)").fetchall()
    tool_request_column = next(
        (row for row in table_info if str(row[1]) == "tool_request_id"),
        None,
    )
    if tool_request_column is None:
        raise RuntimeError("approval_sessions.tool_request_id column is missing")
    if not bool(tool_request_column[3]):
        return False
    action_id_column = next(
        (row for row in table_info if str(row[1]) == "action_id"),
        None,
    )
    if action_id_column is None:
        raise RuntimeError("approval_sessions.action_id column is missing")
    if not bool(action_id_column[3]):
        return False
    if not _has_unique_tool_request_key(connection):
        return False
    tool_invocation_column = next(
        (row for row in table_info if str(row[1]) == "tool_invocation_id"),
        None,
    )
    if tool_invocation_column is None:
        raise RuntimeError("approval_sessions.tool_invocation_id column is missing")
    claimed_at_column = next(
        (row for row in table_info if str(row[1]) == "claimed_at"),
        None,
    )
    if claimed_at_column is None:
        return False
    foreign_keys = connection.execute(
        "PRAGMA foreign_key_list(approval_sessions)"
    ).fetchall()
    tool_invocation_fk = next(
        (row for row in foreign_keys if str(row[3]) == "tool_invocation_id"),
        None,
    )
    if tool_invocation_fk is None:
        raise RuntimeError(
            "approval_sessions.tool_invocation_id foreign key is missing"
        )
    action_fk = next(
        (row for row in foreign_keys if str(row[3]) == "action_id"),
        None,
    )
    if action_fk is None:
        raise RuntimeError("approval_sessions.action_id foreign key is missing")
    return (
        str(tool_invocation_fk[6]).upper() == "SET NULL"
        and str(action_fk[6]).upper() == "CASCADE"
    )


def _has_unique_tool_request_key(connection: sqlite3.Connection) -> bool:
    indexes = connection.execute("PRAGMA index_list(approval_sessions)").fetchall()
    for index_row in indexes:
        index_name = str(index_row[1])
        is_unique = bool(index_row[2])
        if not is_unique:
            continue
        index_columns = connection.execute(
            f"PRAGMA index_info({index_name!r})"
        ).fetchall()
        column_names = [str(column_row[2]) for column_row in index_columns]
        if column_names == ["user_id", "tool_request_id"]:
            return True
    return False


def _rebuild_approval_sessions_for_request_owned_approval(
    connection: sqlite3.Connection,
) -> None:
    connection.execute("DROP TABLE IF EXISTS approval_sessions__rebuild")
    connection.execute(
        """
        CREATE TABLE approval_sessions__rebuild (
            approval_session_id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            action_id TEXT NOT NULL,
            manifest_id TEXT,
            tool_request_id TEXT NOT NULL,
            tool_invocation_id TEXT,
            tool_id TEXT NOT NULL,
            intent_class TEXT NOT NULL,
            approval_source TEXT NOT NULL CHECK (
                approval_source IN ('prompt', 'settings')
            ),
            status TEXT NOT NULL CHECK (
                status IN ('pending', 'approved_once', 'denied', 'interrupted')
            ),
            approved_capabilities_json TEXT NOT NULL CHECK (
                json_valid(approved_capabilities_json)
            ),
            command_summary_json TEXT NOT NULL CHECK (
                json_valid(command_summary_json)
            ),
            requested_at TEXT NOT NULL,
            decided_at TEXT,
            created_at TEXT NOT NULL,
            claimed_at TEXT,
            FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
            FOREIGN KEY (action_id) REFERENCES agent_actions(action_id) ON DELETE CASCADE,
            FOREIGN KEY (tool_invocation_id) REFERENCES tool_invocations(invocation_id) ON DELETE SET NULL,
            CHECK (
                (status = 'pending' AND decided_at IS NULL)
                OR (status != 'pending' AND decided_at IS NOT NULL)
            ),
            CHECK (claimed_at IS NULL OR tool_invocation_id IS NOT NULL),
            CHECK (
                status NOT IN ('pending', 'denied')
                OR (claimed_at IS NULL AND tool_invocation_id IS NULL)
            ),
            UNIQUE (user_id, tool_request_id)
        )
        """
    )
    connection.execute("DROP TABLE approval_sessions")
    connection.execute(
        "ALTER TABLE approval_sessions__rebuild RENAME TO approval_sessions"
    )


def _migrate_approval_preferences(connection: sqlite3.Connection) -> None:
    if not column_exists(
        connection,
        table_name="approval_preferences",
        column_name="approval_mode",
    ):
        return
    connection.execute(
        """
        UPDATE approval_preferences
        SET approval_mode = 'always_allow'
        WHERE approval_mode = 'always_allow_full_access'
        """
    )
    _rebuild_approval_preferences_with_canonical_modes(connection)


def _rebuild_approval_preferences_with_canonical_modes(
    connection: sqlite3.Connection,
) -> None:
    connection.execute("DROP TABLE IF EXISTS approval_preferences__rebuild")
    connection.execute(
        """
        CREATE TABLE approval_preferences__rebuild (
            preference_id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            scope_type TEXT NOT NULL CHECK (scope_type = 'global'),
            scope_ref TEXT,
            approval_mode TEXT NOT NULL CHECK (
                approval_mode IN ('prompt_each_time', 'always_allow')
            ),
            applies_to_json TEXT NOT NULL CHECK (json_valid(applies_to_json)),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            updated_by TEXT NOT NULL CHECK (updated_by = 'user'),
            revoked_at TEXT,
            FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
            CHECK (scope_ref IS NULL)
        )
        """
    )
    connection.execute("DROP TABLE approval_preferences")
    connection.execute(
        "ALTER TABLE approval_preferences__rebuild RENAME TO approval_preferences"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_approval_preferences_user_scope ON approval_preferences(user_id, scope_type, scope_ref, updated_at DESC)"
    )


def _migrate_tool_definitions(connection: sqlite3.Connection) -> None:
    for column_definition in (
        "intent_class TEXT",
        "required_capabilities_json TEXT",
        "timeout_ms INTEGER",
        "llm_guide_json TEXT",
    ):
        add_column_if_missing(
            connection,
            table_name="tool_definitions",
            column_definition=column_definition,
        )
    connection.execute(
        """
        UPDATE tool_definitions
        SET
            intent_class = COALESCE(intent_class, 'read_only'),
            required_capabilities_json = COALESCE(required_capabilities_json, ?),
            llm_guide_json = COALESCE(llm_guide_json, ?)
        WHERE
            intent_class IS NULL
            OR required_capabilities_json IS NULL
            OR llm_guide_json IS NULL
        """,
        (TOOL_DEFINITION_EMPTY_CAPABILITIES_JSON, TOOL_DEFINITION_EMPTY_GUIDE_JSON),
    )


def _migrate_tool_invocations(connection: sqlite3.Connection) -> None:
    add_column_if_missing(
        connection,
        table_name="tool_invocations",
        column_definition="tool_request_id TEXT",
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_tool_invocations_action_started ON tool_invocations(action_id, started_at ASC)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_tool_invocations_step ON tool_invocations(step_id)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_tool_invocations_tool_request ON tool_invocations(tool_request_id)"
    )


def _migrate_tool_outputs(connection: sqlite3.Connection) -> None:
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_tool_outputs_invocation_created ON tool_outputs(invocation_id, created_at ASC)"
    )


def _migrate_tool_redactions(connection: sqlite3.Connection) -> None:
    if not table_exists(connection, table_name="tool_redactions"):
        return
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_tool_redactions_output ON tool_redactions(output_id)"
    )
