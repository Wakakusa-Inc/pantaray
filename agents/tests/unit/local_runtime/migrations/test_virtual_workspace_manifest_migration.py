from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from .support import (
    MANIFEST_RUNTIME_AUTHORITY_MIGRATION_NAME,
    VIRTUAL_WORKSPACE_MANIFEST_MIGRATION_NAME,
    _configure_connection,
    _migrations_before,
    _migrations_through,
    apply_migrations,
    load_default_migrations,
)

TIMESTAMP = "2026-03-23T00:00:00Z"


def test_manifest_tables_enforce_unique_action_and_mount_scope(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "runtime.db"
    _apply_all(db_path)

    with _connection(db_path) as connection:
        _insert_runtime_graph(connection, action_id="action-1")
        _insert_runtime_graph(connection, action_id="action-2")
        _insert_workspace_manifest(connection, action_id="action-1")

        with pytest.raises(sqlite3.IntegrityError):
            _insert_workspace_manifest(
                connection,
                manifest_id="manifest-duplicate-action",
                action_id="action-1",
            )

        _insert_workspace_manifest(
            connection,
            manifest_id="manifest-2",
            action_id="action-2",
        )
        _insert_manifest_mount(connection)

        with pytest.raises(sqlite3.IntegrityError):
            _insert_manifest_mount(
                connection,
                mount_id="mount-duplicate-root",
                virtual_name="repo",
                virtual_path="/repo",
                canonical_real_path="/tmp/repo",
            )
        with pytest.raises(sqlite3.IntegrityError):
            _insert_manifest_mount(
                connection,
                mount_id="mount-invalid-source",
                source_type="workspace",
                virtual_name="invalid",
                virtual_path="/invalid",
                canonical_real_path="/tmp/invalid",
            )


def test_manifest_and_file_references_follow_action_lifecycle(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "runtime.db"
    _apply_all(db_path)

    with _connection(db_path) as connection:
        _insert_runtime_graph(connection, action_id="action-1")
        _insert_workspace_manifest(connection, action_id="action-1")
        _insert_manifest_mount(connection)
        _insert_file_reference(connection)

        with pytest.raises(sqlite3.IntegrityError):
            _insert_file_reference(
                connection,
                file_reference_id="file-reference-duplicate",
            )

        connection.execute(
            "DELETE FROM tool_invocations WHERE invocation_id = 'invocation-1'"
        )
        assert _fetchone(
            connection,
            "SELECT tool_invocation_id FROM file_references WHERE file_reference_id = 'file-reference-1'",
        ) == (None,)
        assert _fetchone(
            connection,
            "SELECT execution_session_id FROM workspace_manifests WHERE manifest_id = 'manifest-1'",
        ) == ("execution-session-1",)

        connection.execute(
            "DELETE FROM execution_sessions WHERE execution_session_id = 'execution-session-1'"
        )
        assert _fetchone(
            connection,
            "SELECT execution_session_id FROM workspace_manifests WHERE manifest_id = 'manifest-1'",
        ) == (None,)
        assert _count(connection, "file_references") == 1

        connection.execute("DELETE FROM agent_actions WHERE action_id = 'action-1'")
        assert _count(connection, "workspace_manifests") == 0
        assert _count(connection, "file_references") == 0


def test_approval_sessions_reject_persisted_status_after_cutover(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "runtime.db"
    _apply_all(db_path)

    with _connection(db_path) as connection:
        _insert_runtime_graph(connection, action_id="action-1")

        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO approval_sessions(
                    approval_session_id, user_id, action_id, manifest_id,
                    tool_request_id, tool_id, intent_class, approval_source, status,
                    approved_capabilities_json, command_summary_json,
                    requested_at, decided_at, created_at
                ) VALUES (
                    'approval-1', 'user-1', 'action-1', NULL,
                    'request-1', 'apply_patch', 'surgical_edit', 'settings',
                    'approved_and_persisted', '{}', '{}', ?, ?, ?
                )
                """,
                (TIMESTAMP, TIMESTAMP, TIMESTAMP),
            )


def test_approval_sessions_accept_interrupted_status_after_cutover(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "runtime.db"
    _apply_all(db_path)

    with _connection(db_path) as connection:
        _insert_runtime_graph(connection, action_id="action-1")
        connection.execute(
            """
            INSERT INTO approval_sessions(
                approval_session_id, user_id, action_id, manifest_id,
                tool_request_id, tool_id, intent_class, approval_source, status,
                approved_capabilities_json, command_summary_json,
                requested_at, decided_at, created_at
            ) VALUES (
                'approval-1', 'user-1', 'action-1', NULL,
                'request-1', 'apply_patch', 'surgical_edit', 'prompt',
                'interrupted', '{}', '{}', ?, ?, ?
            )
            """,
            (TIMESTAMP, TIMESTAMP, TIMESTAMP),
        )

        assert _count(connection, "approval_sessions") == 1


def test_legacy_pending_approval_is_dropped_without_action_side_effects(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "runtime.db"
    migrations = load_default_migrations()

    apply_migrations(
        db_path=db_path,
        busy_timeout_ms=1_000,
        migrations=_migrations_before(
            migrations, VIRTUAL_WORKSPACE_MANIFEST_MIGRATION_NAME
        ),
    )
    with _connection(db_path) as connection:
        _insert_runtime_graph(connection, action_id="action-1")
        connection.execute(
            """
            INSERT INTO approval_sessions(
                approval_session_id, user_id, action_id, workspace_id,
                tool_request_id, tool_invocation_id, tool_id, intent_class,
                approval_source, status, approved_capabilities_json,
                command_summary_json, requested_at, decided_at, created_at, claimed_at
            ) VALUES (
                'approval-1', 'user-1', 'action-1', 'workspace-1',
                'request-1', NULL, 'apply_patch', 'surgical_edit',
                'prompt', 'pending', '{}', '{}', ?, NULL, ?, NULL
            )
            """,
            (TIMESTAMP, TIMESTAMP),
        )

    apply_migrations(
        db_path=db_path,
        busy_timeout_ms=1_000,
        migrations=_migrations_through(
            migrations,
            VIRTUAL_WORKSPACE_MANIFEST_MIGRATION_NAME,
        ),
    )

    with _connection(db_path) as connection:
        approval_count = _count(connection, "approval_sessions")
        approval_row = connection.execute(
            "SELECT 1 FROM approval_sessions WHERE approval_session_id = 'approval-1'",
        ).fetchone()
        action_row = _fetchone(
            connection,
            "SELECT status, error FROM agent_actions WHERE action_id = 'action-1'",
        )
        suggestion_row = _fetchone(
            connection,
            """
            SELECT action_status, action_failure_code, action_failure_stage
            FROM agent_suggestions
            WHERE suggestion_id = 'suggestion-action-1'
            """,
        )

    assert approval_count == 0
    assert approval_row is None
    assert action_row == ("processing", None)
    assert suggestion_row == (None, None, None)


def test_runtime_tables_use_manifest_authority_not_workspace_id(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "runtime.db"
    _apply_all(db_path)

    with _connection(db_path) as connection:
        execution_columns = _table_columns(connection, "execution_sessions")
        invocation_columns = _table_columns(connection, "tool_invocations")
        approval_columns = _table_columns(connection, "approval_sessions")

    assert "workspace_id" not in execution_columns
    assert "manifest_id" not in execution_columns
    assert "workspace_id" not in invocation_columns
    assert "manifest_id" in invocation_columns
    assert "command_summary" not in invocation_columns
    assert "command_summary_json" in invocation_columns
    assert "workspace_id" not in approval_columns
    assert "manifest_id" in approval_columns


def test_manifest_authority_cutover_recreates_runtime_tables(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "runtime.db"
    migrations = load_default_migrations()

    apply_migrations(
        db_path=db_path,
        busy_timeout_ms=1_000,
        migrations=_migrations_before(
            migrations, MANIFEST_RUNTIME_AUTHORITY_MIGRATION_NAME
        ),
    )
    with _connection(db_path) as connection:
        _insert_runtime_graph(connection, action_id="action-1")
        _insert_workspace_manifest(connection, action_id="action-1")
        _insert_manifest_mount(connection)
        _insert_file_reference(connection)

    apply_migrations(
        db_path=db_path,
        busy_timeout_ms=1_000,
        migrations=_migrations_through(
            migrations, MANIFEST_RUNTIME_AUTHORITY_MIGRATION_NAME
        ),
    )

    with _connection(db_path) as connection:
        tables = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        assert "workspaces" not in tables
        assert "allowed_roots" not in tables
        assert _count(connection, "execution_sessions") == 0
        assert _count(connection, "workspace_manifests") == 0
        assert _count(connection, "workspace_manifest_mounts") == 0
        assert _count(connection, "tool_invocations") == 0
        assert _count(connection, "tool_outputs") == 0
        assert _count(connection, "tool_runtime_resources") == 0
        assert _count(connection, "tool_runtime_resource_events") == 0
        assert _count(connection, "approval_sessions") == 0
        assert _count(connection, "file_references") == 0
        assert _count(connection, "command_invocation_audits") == 0
        assert _count(connection, "agent_actions") == 1


def test_manifest_authority_cutover_replays_stale_version_37_checksum(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "runtime.db"
    migrations = load_default_migrations()
    migration_37 = next(
        m for m in migrations if m.name == MANIFEST_RUNTIME_AUTHORITY_MIGRATION_NAME
    )
    apply_migrations(
        db_path=db_path,
        busy_timeout_ms=1_000,
        migrations=_migrations_before(
            migrations, MANIFEST_RUNTIME_AUTHORITY_MIGRATION_NAME
        ),
    )
    with _connection(db_path) as connection:
        connection.execute(
            """
            UPDATE schema_versions
            SET current_version = ?, migration_name = ?, checksum = ?
            WHERE component = 'local_runtime'
            """,
            (migration_37.version, migration_37.name, "stale-version-37-checksum"),
        )
    apply_migrations(
        db_path=db_path,
        busy_timeout_ms=1_000,
        migrations=_migrations_through(
            migrations, MANIFEST_RUNTIME_AUTHORITY_MIGRATION_NAME
        ),
    )
    with _connection(db_path) as connection:
        invocation_columns = _table_columns(connection, "tool_invocations")
        checksum_row = connection.execute(
            "SELECT checksum FROM schema_versions WHERE component = 'local_runtime'"
        ).fetchone()

    assert "command_summary_json" in invocation_columns
    assert "command_summary" not in invocation_columns
    assert checksum_row == (migration_37.checksum_sha256,)


def _apply_all(db_path: Path) -> None:
    apply_migrations(
        db_path=db_path,
        busy_timeout_ms=1_000,
        migrations=load_default_migrations(),
    )


def _connection(db_path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(db_path)
    _configure_connection(connection, busy_timeout_ms=1_000)
    return connection


def _insert_runtime_graph(connection: sqlite3.Connection, *, action_id: str) -> None:
    _insert_user(connection)
    suggestion_id = f"suggestion-{action_id}"
    connection.execute(
        """
        INSERT INTO agent_suggestions(
            suggestion_id, user_id, status, created_at, updated_at
        ) VALUES (?, 'user-1', 'processing', ?, ?)
        """,
        (suggestion_id, TIMESTAMP, TIMESTAMP),
    )
    action_columns = {
        str(row[1]) for row in connection.execute("PRAGMA table_info(agent_actions)")
    }
    if "initial_user_message_id" in action_columns:
        connection.execute(
            """
            INSERT INTO agent_actions(
                action_id, user_id, suggestion_id, initial_user_message_id,
                status, execution_target_json, final_output, prompt_name,
                prompt_version, created_at, updated_at
            ) VALUES (
                ?, 'user-1', ?, ?, 'processing', '{"kind":"scratch"}', '',
                'action/executing', '1.0', ?, ?
            )
            """,
            (action_id, suggestion_id, f"message-{action_id}", TIMESTAMP, TIMESTAMP),
        )
    else:
        connection.execute(
            """
            INSERT INTO agent_actions(
                action_id, user_id, suggestion_id, status, final_output,
                prompt_name, prompt_version, created_at, updated_at
            ) VALUES (
                ?, 'user-1', ?, 'processing', '', 'action/executing', '1.0', ?, ?
            )
            """,
            (action_id, suggestion_id, TIMESTAMP, TIMESTAMP),
        )
    _insert_workspace_runtime(connection)
    _insert_tool_definition(connection)
    _insert_execution_session(connection, action_id=action_id)
    _insert_tool_invocation(connection, action_id=action_id)


def _insert_user(connection: sqlite3.Connection, user_id: str = "user-1") -> None:
    connection.execute(
        """
        INSERT OR IGNORE INTO users(user_id, ui_language, created_at, updated_at)
        VALUES (?, 'ja', ?, ?)
        """,
        (user_id, TIMESTAMP, TIMESTAMP),
    )


def _insert_workspace_runtime(connection: sqlite3.Connection) -> None:
    if "workspaces" not in _existing_table_names(connection):
        return
    connection.execute(
        """
        INSERT OR IGNORE INTO allowed_roots(
            root_id, user_id, bookmark_data, normalized_path, access_mode, created_at, updated_at
        ) VALUES ('root-1', 'user-1', X'00', '/tmp/repo', 'read_write', ?, ?)
        """,
        (TIMESTAMP, TIMESTAMP),
    )
    connection.execute(
        """
        INSERT OR IGNORE INTO workspaces(
            workspace_id, user_id, kind, root_id, normalized_path, repo_root_path,
            vcs_kind, toolchain_hint_json, trust_level, default_exec_policy_json,
            created_at, updated_at
        ) VALUES (
            'workspace-1', 'user-1', 'user_repo', 'root-1', '/tmp/repo', '/tmp/repo',
            'git', '{}', 'user_selected', '{}', ?, ?
        )
        """,
        (TIMESTAMP, TIMESTAMP),
    )


def _insert_tool_definition(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        INSERT OR IGNORE INTO tool_definitions(
            tool_id, tool_name, tool_description, category, risk_level,
            input_schema_json, is_enabled, version, created_at, updated_at,
            intent_class, required_capabilities_json, timeout_ms, llm_guide_json
        ) VALUES (
            'apply_patch', 'apply_patch', 'Apply patch', 'edit', 'medium',
            '{}', 1, '1', ?, ?, 'surgical_edit', '[]', 1000, '{}'
        )
        """,
        (TIMESTAMP, TIMESTAMP),
    )


def _insert_execution_session(
    connection: sqlite3.Connection, *, action_id: str
) -> None:
    columns = _table_columns(connection, "execution_sessions")
    session_id = f"execution-session-{action_id.rsplit('-', 1)[-1]}"
    if "workspace_id" in columns:
        connection.execute(
            """
            INSERT INTO execution_sessions(
                execution_session_id, user_id, action_id, workspace_id, exec_mode,
                cwd_path, action_temp_dir, app_runtime_python, network_policy,
                capability_snapshot_json, status, started_at
            ) VALUES (
                ?, 'user-1', ?, 'workspace-1',
                'workspace_command', '/tmp/repo', '/tmp/action-temp', '/tmp/python',
                'disabled', '[]', 'running', ?
            )
            """,
            (session_id, action_id, TIMESTAMP),
        )
        return
    connection.execute(
        """
        INSERT INTO execution_sessions(
            execution_session_id, user_id, action_id, exec_mode, cwd_path,
            action_temp_dir, app_runtime_python, network_policy,
            capability_snapshot_json, status, started_at
        ) VALUES (
            ?, 'user-1', ?, 'workspace_command',
            '/tmp/repo', '/tmp/action-temp', '/tmp/python', 'disabled',
            '[]', 'running', ?
        )
        """,
        (session_id, action_id, TIMESTAMP),
    )


def _insert_tool_invocation(
    connection: sqlite3.Connection,
    *,
    action_id: str,
) -> None:
    columns = _table_columns(connection, "tool_invocations")
    authority_column = "workspace_id" if "workspace_id" in columns else "manifest_id"
    authority_value = "workspace-1" if authority_column == "workspace_id" else None
    summary_column = (
        "command_summary_json"
        if "command_summary_json" in columns
        else "command_summary"
    )
    summary_value = (
        '{"summary_kind":"apply_patch","target_paths":[]}'
        if summary_column == "command_summary_json"
        else "Apply patch"
    )
    suffix = action_id.rsplit("-", 1)[-1]
    connection.execute(
        f"""
        INSERT INTO tool_invocations(
            invocation_id, user_id, action_id, tool_id, {authority_column},
            execution_session_id, intent_class, {summary_column}, started_at,
            completed_at, status
        ) VALUES (
            ?, 'user-1', ?, 'apply_patch', ?, ?,
            'surgical_edit', ?, ?, ?, 'completed'
        )
        """,
        (
            f"invocation-{suffix}",
            action_id,
            authority_value,
            f"execution-session-{suffix}",
            summary_value,
            TIMESTAMP,
            TIMESTAMP,
        ),
    )


def _insert_workspace_manifest(
    connection: sqlite3.Connection,
    *,
    action_id: str,
    manifest_id: str = "manifest-1",
) -> None:
    if "virtual_root_path" in _table_columns(connection, "workspace_manifests"):
        connection.execute(
            """
            INSERT INTO workspace_manifests(
                manifest_id, user_id, action_id, execution_session_id,
                virtual_root_path, scratch_root_path, created_at, status
            ) VALUES (
                ?, 'user-1', ?, 'execution-session-1',
                '/tmp/legacy-virtual-root', '/tmp/scratch-root', ?, 'ready'
            )
            """,
            (manifest_id, action_id, TIMESTAMP),
        )
        return
    connection.execute(
        """
        INSERT INTO workspace_manifests(
            manifest_id, user_id, action_id, execution_session_id,
            scratch_root_path, created_at, status
        ) VALUES (?, 'user-1', ?, 'execution-session-1', '/tmp/scratch-root', ?, 'ready')
        """,
        (manifest_id, action_id, TIMESTAMP),
    )


def _insert_manifest_mount(
    connection: sqlite3.Connection,
    *,
    mount_id: str = "mount-1",
    source_type: str = "folder",
    virtual_name: str = "repo",
    virtual_path: str = "/repo",
    canonical_real_path: str = "/tmp/repo",
) -> None:
    if "workspace_manifest_mounts" not in _existing_table_names(connection):
        connection.execute(
            """
            INSERT INTO workspace_manifest_roots(
                root_id, manifest_id, source_type, source_id, display_name,
                canonical_real_path, real_path, can_read, can_apply_patch,
                can_process_read, can_process_write, created_at
            ) VALUES (
                ?, 'manifest-1', ?, 'workspace-folder-1', ?,
                ?, ?, 1, 1, 1, 1, ?
            )
            """,
            (
                mount_id,
                source_type,
                virtual_name,
                canonical_real_path,
                canonical_real_path,
                TIMESTAMP,
            ),
        )
        return
    connection.execute(
        """
        INSERT INTO workspace_manifest_mounts(
            mount_id, manifest_id, source_type, source_id, virtual_name, virtual_path,
            display_name, canonical_real_path, real_path, can_read, can_apply_patch,
            can_process_read, can_process_write, created_at
        ) VALUES (?, 'manifest-1', ?, 'workspace-folder-1', ?, ?, ?, ?, ?, 1, 1, 1, 1, ?)
        """,
        (
            mount_id,
            source_type,
            virtual_name,
            virtual_path,
            virtual_name,
            canonical_real_path,
            canonical_real_path,
            TIMESTAMP,
        ),
    )


def _insert_file_reference(
    connection: sqlite3.Connection,
    *,
    file_reference_id: str = "file-reference-1",
) -> None:
    if "virtual_path" not in _table_columns(connection, "file_references"):
        connection.execute(
            """
            INSERT INTO file_references(
                file_reference_id, user_id, action_id, manifest_id, root_id,
                tool_invocation_id, local_path, canonical_local_path, created_at
            ) VALUES (
                ?, 'user-1', 'action-1', 'manifest-1', 'mount-1',
                'invocation-1', '/tmp/repo/src/app.py', '/tmp/repo/src/app.py', ?
            )
            """,
            (file_reference_id, TIMESTAMP),
        )
        return
    connection.execute(
        """
        INSERT INTO file_references(
            file_reference_id, user_id, action_id, manifest_id, mount_id,
            tool_invocation_id, virtual_path, created_at
        ) VALUES (
            ?, 'user-1', 'action-1', 'manifest-1', 'mount-1',
            'invocation-1', '/repo/src/app.py', ?
        )
        """,
        (file_reference_id, TIMESTAMP),
    )


def _fetchone(connection: sqlite3.Connection, sql: str) -> tuple[object, ...]:
    row = connection.execute(sql).fetchone()
    assert row is not None
    return tuple(row)


def _count(connection: sqlite3.Connection, table_name: str) -> int:
    row = _fetchone(connection, f"SELECT COUNT(*) FROM {table_name}")
    return int(row[0])


def _table_columns(connection: sqlite3.Connection, table_name: str) -> set[str]:
    rows = connection.execute(f"PRAGMA table_info({table_name})").fetchall()
    return {str(row[1]) for row in rows}


def _existing_table_names(connection: sqlite3.Connection) -> set[str]:
    rows = connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    return {str(row[0]) for row in rows}
