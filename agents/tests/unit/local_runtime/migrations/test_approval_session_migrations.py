from __future__ import annotations

import sqlite3
from pathlib import Path

from pantaray_agents.local_runtime.storage.migrations.phase3 import (
    apply_tooling_contract_migration,
)

from .support import (
    _configure_connection,
    _insert_user,
    apply_migrations,
    load_default_migrations,
)


def _seed_legacy_approval_sessions_fixture(
    *,
    db_path: Path,
    consumed_at: str | None,
    claimed_at: str | None,
) -> None:
    with sqlite3.connect(db_path) as connection:
        _insert_user(connection, "user-1")
        connection.execute(
            """
            INSERT INTO agent_suggestions(
                suggestion_id,
                user_id,
                status,
                created_at,
                updated_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                "suggestion-1",
                "user-1",
                "processing",
                "2026-03-23T00:00:00Z",
                "2026-03-23T00:00:01Z",
            ),
        )
        connection.execute(
            """
            INSERT INTO agent_actions(
                action_id,
                suggestion_id,
                user_id,
                status,
                final_output,
                prompt_name,
                prompt_version,
                created_at,
                updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "action-1",
                "suggestion-1",
                "user-1",
                "success",
                "legacy final output",
                "action/executing",
                "1.0",
                "2026-03-23T00:00:02Z",
                "2026-03-23T00:00:03Z",
            ),
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
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "workspace-1",
                "user-1",
                "user_folder",
                None,
                "/tmp/workspace-1",
                None,
                "none",
                "{}",
                "user_selected",
                "{}",
                "2026-03-23T00:00:00Z",
                "2026-03-23T00:00:00Z",
            ),
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
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "session-1",
                "user-1",
                "action-1",
                None,
                "workspace-1",
                "workspace_command",
                ".",
                None,
                None,
                "deny",
                "{}",
                None,
                "running",
                "2026-03-23T00:00:03Z",
                None,
                None,
            ),
        )
        connection.execute(
            """
            INSERT INTO tool_invocations(
                invocation_id,
                user_id,
                action_id,
                step_id,
                tool_id,
                workspace_id,
                execution_session_id,
                cwd,
                timeout_ms,
                intent_class,
                network_policy,
                command_summary,
                capability_snapshot_json,
                started_at,
                completed_at,
                status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "invocation-1",
                "user-1",
                "action-1",
                "step-1",
                "bash",
                "workspace-1",
                "session-1",
                ".",
                None,
                "process_exec_local",
                "deny",
                "pwd",
                "{}",
                "2026-03-23T00:00:05Z",
                None,
                "running",
            ),
        )
        connection.execute("DROP TABLE approval_sessions")
        connection.execute(
            """
            CREATE TABLE approval_sessions (
                approval_session_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                action_id TEXT NOT NULL,
                workspace_id TEXT,
                tool_request_id TEXT NOT NULL,
                tool_invocation_id TEXT,
                tool_id TEXT NOT NULL,
                intent_class TEXT NOT NULL,
                approval_source TEXT NOT NULL,
                status TEXT NOT NULL,
                approved_capabilities_json TEXT NOT NULL,
                command_summary_json TEXT NOT NULL,
                requested_at TEXT NOT NULL,
                decided_at TEXT,
                created_at TEXT NOT NULL,
                consumed_at TEXT,
                claimed_at TEXT
            )
            """
        )
        connection.execute(
            """
            INSERT INTO approval_sessions(
                approval_session_id,
                user_id,
                action_id,
                workspace_id,
                tool_request_id,
                tool_invocation_id,
                tool_id,
                intent_class,
                approval_source,
                status,
                approved_capabilities_json,
                command_summary_json,
                requested_at,
                decided_at,
                created_at,
                consumed_at,
                claimed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "approval-1",
                "user-1",
                "action-1",
                None,
                "request-1",
                "invocation-1",
                "bash",
                "process_exec_local",
                "prompt",
                "approved_once",
                '{"required_capabilities":["process_exec_local"]}',
                '{"command":"pwd"}',
                "2026-03-23T00:00:04Z",
                "2026-03-23T00:00:05Z",
                "2026-03-23T00:00:04Z",
                consumed_at,
                claimed_at,
            ),
        )


def test_apply_migrations_drops_legacy_approval_sessions_when_consumed_at_exists(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "runtime.db"

    apply_migrations(
        db_path=db_path,
        busy_timeout_ms=1_000,
        migrations=load_default_migrations()[:8],
    )
    _seed_legacy_approval_sessions_fixture(
        db_path=db_path,
        consumed_at="2026-03-23T00:00:06Z",
        claimed_at=None,
    )

    with sqlite3.connect(db_path) as connection:
        _configure_connection(connection, busy_timeout_ms=1_000)
        apply_tooling_contract_migration(connection)

    with sqlite3.connect(db_path) as connection:
        approval_session_columns = {
            str(row[1])
            for row in connection.execute("PRAGMA table_info(approval_sessions)")
        }
        approval_session_count = connection.execute(
            "SELECT COUNT(*) FROM approval_sessions"
        ).fetchone()
        ddl_row = connection.execute(
            """
            SELECT sql
            FROM sqlite_master
            WHERE type = 'table' AND name = 'approval_sessions'
            """
        ).fetchone()

    assert "consumed_at" not in approval_session_columns
    assert "claimed_at" in approval_session_columns
    assert approval_session_count == (0,)
    assert ddl_row is not None
    ddl = str(ddl_row[0])
    assert "CHECK (claimed_at IS NULL OR tool_invocation_id IS NOT NULL)" in ddl
    assert "UNIQUE (user_id, tool_request_id)" in ddl


def test_apply_migrations_discards_existing_claimed_at_with_legacy_approval_session(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "runtime.db"

    apply_migrations(
        db_path=db_path,
        busy_timeout_ms=1_000,
        migrations=load_default_migrations()[:8],
    )
    _seed_legacy_approval_sessions_fixture(
        db_path=db_path,
        consumed_at="2026-03-23T00:00:06Z",
        claimed_at="2026-03-23T00:00:07Z",
    )

    with sqlite3.connect(db_path) as connection:
        _configure_connection(connection, busy_timeout_ms=1_000)
        apply_tooling_contract_migration(connection)

    with sqlite3.connect(db_path) as connection:
        approval_session_columns = {
            str(row[1])
            for row in connection.execute("PRAGMA table_info(approval_sessions)")
        }
        approval_session_count = connection.execute(
            "SELECT COUNT(*) FROM approval_sessions"
        ).fetchone()

    assert "consumed_at" not in approval_session_columns
    assert approval_session_count == (0,)
