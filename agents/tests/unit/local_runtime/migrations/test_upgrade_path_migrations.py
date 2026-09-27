from __future__ import annotations

import sqlite3
from pathlib import Path

from .support import (
    LATEST_LOCAL_RUNTIME_SCHEMA_VERSION,
    _insert_user,
    _migrations_before,
    apply_migrations,
    load_default_migrations,
)

ACTION_CREATION_CUTOVER_MIGRATION_NAME = "0082_action_creation_cutover.sql"


def test_apply_migrations_upgrades_existing_version10_db_with_resource_events(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "runtime.db"

    apply_migrations(
        db_path=db_path,
        busy_timeout_ms=1_000,
        migrations=load_default_migrations()[:10],
    )

    apply_migrations(
        db_path=db_path,
        busy_timeout_ms=1_000,
        migrations=load_default_migrations(),
    )

    with sqlite3.connect(db_path) as connection:
        version_row = connection.execute(
            """
            SELECT current_version
            FROM schema_versions
            WHERE component = 'local_runtime'
            """
        ).fetchone()
        table_row = connection.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table' AND name = 'tool_runtime_resource_events'
            """
        ).fetchone()

    assert version_row is not None
    assert int(version_row[0]) == LATEST_LOCAL_RUNTIME_SCHEMA_VERSION
    assert table_row == ("tool_runtime_resource_events",)


def test_apply_migrations_upgrades_existing_version11_db_with_runtime_lock_ledger(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "runtime.db"

    apply_migrations(
        db_path=db_path,
        busy_timeout_ms=1_000,
        migrations=load_default_migrations()[:11],
    )

    apply_migrations(
        db_path=db_path,
        busy_timeout_ms=1_000,
        migrations=load_default_migrations(),
    )

    with sqlite3.connect(db_path) as connection:
        version_row = connection.execute(
            """
            SELECT current_version
            FROM schema_versions
            WHERE component = 'local_runtime'
            """
        ).fetchone()
        table_row = connection.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table' AND name = 'runtime_lock_resources'
            """
        ).fetchone()

    assert version_row is not None
    assert int(version_row[0]) == LATEST_LOCAL_RUNTIME_SCHEMA_VERSION
    assert table_row == ("runtime_lock_resources",)


def test_apply_migrations_upgrades_existing_version12_db_with_socket_scope_removal(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "runtime.db"

    apply_migrations(
        db_path=db_path,
        busy_timeout_ms=1_000,
        migrations=load_default_migrations()[:12],
    )

    apply_migrations(
        db_path=db_path,
        busy_timeout_ms=1_000,
        migrations=load_default_migrations(),
    )

    with sqlite3.connect(db_path) as connection:
        version_row = connection.execute(
            """
            SELECT current_version
            FROM schema_versions
            WHERE component = 'local_runtime'
            """
        ).fetchone()

    assert version_row is not None
    assert int(version_row[0]) == LATEST_LOCAL_RUNTIME_SCHEMA_VERSION


def test_apply_migrations_upgrades_existing_version13_db_with_workspace_lock_owner_token(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "runtime.db"

    apply_migrations(
        db_path=db_path,
        busy_timeout_ms=1_000,
        migrations=load_default_migrations()[:13],
    )

    apply_migrations(
        db_path=db_path,
        busy_timeout_ms=1_000,
        migrations=load_default_migrations(),
    )

    with sqlite3.connect(db_path) as connection:
        version_row = connection.execute(
            """
            SELECT current_version
            FROM schema_versions
            WHERE component = 'local_runtime'
            """
        ).fetchone()
        columns = connection.execute(
            "PRAGMA table_info(tool_runtime_resources)"
        ).fetchall()

    assert version_row is not None
    assert int(version_row[0]) == LATEST_LOCAL_RUNTIME_SCHEMA_VERSION
    assert any(column[1] == "lock_id" for column in columns)


def test_apply_migrations_drops_legacy_socket_resources_on_upgrade(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "runtime.db"

    apply_migrations(
        db_path=db_path,
        busy_timeout_ms=1_000,
        migrations=load_default_migrations()[:12],
    )
    with sqlite3.connect(db_path) as connection:
        with connection:
            connection.execute("DROP TABLE tool_runtime_resources")
            connection.execute(
                """
                CREATE TABLE tool_runtime_resources (
                    resource_id TEXT PRIMARY KEY,
                    execution_session_id TEXT NOT NULL,
                    tool_invocation_id TEXT,
                    action_id TEXT,
                    resource_kind TEXT NOT NULL CHECK (
                        resource_kind IN ('process_group', 'temp_file', 'temp_dir', 'socket', 'lock')
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
            _insert_user(connection, "user-1")
            connection.execute(
                """
                INSERT INTO agent_suggestions(
                    suggestion_id,
                    user_id,
                    status,
                    created_at,
                    updated_at
                ) VALUES (
                    'suggestion-1',
                    'user-1',
                    'processing',
                    '2026-03-23T00:00:00Z',
                    '2026-03-23T00:00:00Z'
                )
                """
            )
            connection.execute(
                """
                INSERT INTO agent_actions(
                    action_id,
                    user_id,
                    suggestion_id,
                    status,
                    final_output,
                    prompt_name,
                    prompt_version,
                    created_at,
                    updated_at
                ) VALUES (
                    'action-1',
                    'user-1',
                    'suggestion-1',
                    'processing',
                    '',
                    'action/executing',
                    '1.0',
                    '2026-03-23T00:00:00Z',
                    '2026-03-23T00:00:00Z'
                )
                """
            )
            connection.execute(
                """
                INSERT INTO workspaces(
                    workspace_id,
                    user_id,
                    kind,
                    root_id,
                    normalized_path,
                    repo_root_path,
                    vcs_kind,
                    toolchain_hint_json,
                    trust_level,
                    default_exec_policy_json,
                    created_at,
                    updated_at
                ) VALUES (
                    'workspace-1',
                    'user-1',
                    'scratch',
                    NULL,
                    '/tmp/workspace',
                    NULL,
                    'none',
                    '{}',
                    'ephemeral',
                    '{}',
                    '2026-03-23T00:00:00Z',
                    '2026-03-23T00:00:00Z'
                )
                """
            )
            connection.execute(
                """
                INSERT INTO execution_sessions(
                    execution_session_id,
                    user_id,
                    action_id,
                    parent_execution_session_id,
                    workspace_id,
                    exec_mode,
                    cwd_path,
                    action_temp_dir,
                    app_runtime_python,
                    network_policy,
                    capability_snapshot_json,
                    tool_allowlist_json,
                    status,
                    started_at,
                    completed_at,
                    expires_at
                ) VALUES (
                    'execution-session-1',
                    'user-1',
                    'action-1',
                    NULL,
                    'workspace-1',
                    'workspace_command',
                    '/tmp/workspace',
                    NULL,
                    NULL,
                    'cloud-proxy-only',
                    '{}',
                    NULL,
                    'running',
                    '2026-03-23T00:00:00Z',
                    NULL,
                    NULL
                )
                """
            )
            connection.execute(
                """
                INSERT INTO tool_runtime_resources(
                    resource_id,
                    execution_session_id,
                    tool_invocation_id,
                    action_id,
                    resource_kind,
                    status,
                    pid,
                    pgid,
                    process_start_signature,
                    resource_path,
                    created_at,
                    updated_at,
                    cleaned_at,
                    cleanup_error,
                    cleanup_attempts
                ) VALUES (
                    'legacy-socket-resource',
                    'execution-session-1',
                    NULL,
                    'action-1',
                    'socket',
                    'active',
                    NULL,
                    NULL,
                    NULL,
                    '/tmp/legacy.socket',
                    '2026-03-23T00:00:00Z',
                    '2026-03-23T00:00:00Z',
                    NULL,
                    NULL,
                    0
                )
                """
            )
            connection.execute("DELETE FROM migration_journal")

    apply_migrations(
        db_path=db_path,
        busy_timeout_ms=1_000,
        migrations=_migrations_before(
            load_default_migrations(),
            ACTION_CREATION_CUTOVER_MIGRATION_NAME,
        ),
    )

    with sqlite3.connect(db_path) as connection:
        row = connection.execute(
            "SELECT COUNT(*) FROM tool_runtime_resources"
        ).fetchone()

    assert row == (0,)
