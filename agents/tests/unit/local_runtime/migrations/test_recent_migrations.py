from __future__ import annotations

import sqlite3
from pathlib import Path

from .support import (
    ACTION_TERMINAL_RUNTIME_REPAIRS_MIGRATION_NAME,
    LATEST_LOCAL_RUNTIME_MIGRATION_NAME,
    LATEST_LOCAL_RUNTIME_SCHEMA_VERSION,
    POST_ACTION_PIPELINE_PROCESS_KIND_MIGRATION_NAME,
    REMOVE_INTERVENTION_MODE_MIGRATION_NAME,
    _configure_connection,
    _insert_user,
    _migrations_before,
    _migrations_through,
    apply_migrations,
    load_default_migrations,
)


def test_apply_migration_0029_repairs_stale_v28_triggers_before_rebuilding_audits(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "runtime.db"
    migrations = load_default_migrations()
    migrations_through_v28 = _migrations_through(
        migrations,
        REMOVE_INTERVENTION_MODE_MIGRATION_NAME,
    )
    apply_migrations(
        db_path=db_path,
        busy_timeout_ms=1_000,
        migrations=migrations_through_v28,
    )

    with sqlite3.connect(db_path) as connection:
        _configure_connection(connection, busy_timeout_ms=1_000)
        with connection:
            trigger_rows = connection.execute(
                """
                SELECT name, sql
                FROM sqlite_master
                WHERE type = 'trigger'
                  AND tbl_name = 'agent_actions'
                  AND name IN (
                      'reject_message_only_agent_action_insert',
                      'reject_message_only_agent_action_update'
                  )
                ORDER BY name ASC
                """
            ).fetchall()
            for trigger_name, trigger_sql in trigger_rows:
                connection.execute(f'DROP TRIGGER IF EXISTS "{trigger_name}"')
                connection.execute(
                    str(trigger_sql).replace(
                        "agent_suggestions",
                        "agent_suggestions_legacy_v28",
                    )
                )

    apply_migrations(
        db_path=db_path,
        busy_timeout_ms=1_000,
        migrations=migrations,
    )

    with sqlite3.connect(db_path) as connection:
        _configure_connection(connection, busy_timeout_ms=1_000)
        trigger_rows = connection.execute(
            """
            SELECT sql
            FROM sqlite_master
            WHERE type = 'trigger'
              AND tbl_name = 'agent_actions'
              AND name IN (
                  'reject_message_only_agent_action_insert',
                  'reject_message_only_agent_action_update'
              )
            ORDER BY name ASC
            """
        ).fetchall()
        schema_row = connection.execute(
            """
            SELECT current_version, migration_name
            FROM schema_versions
            WHERE component = 'local_runtime'
            """
        ).fetchone()
    assert all(
        "agent_suggestions_legacy_v28" not in str(row[0]) for row in trigger_rows
    )
    assert schema_row == (
        LATEST_LOCAL_RUNTIME_SCHEMA_VERSION,
        LATEST_LOCAL_RUNTIME_MIGRATION_NAME,
    )


def test_apply_migration_0032_repairs_terminal_runtime_gaps(tmp_path: Path) -> None:
    db_path = tmp_path / "runtime.db"
    migrations = load_default_migrations()
    migrations_through_v31 = _migrations_through(
        migrations,
        POST_ACTION_PIPELINE_PROCESS_KIND_MIGRATION_NAME,
    )
    apply_migrations(
        db_path=db_path,
        busy_timeout_ms=1_000,
        migrations=migrations_through_v31,
    )

    with sqlite3.connect(db_path) as connection:
        _configure_connection(connection, busy_timeout_ms=1_000)
        with connection:
            _insert_user(connection, "user-1")
            connection.execute(
                """
                INSERT INTO processes(
                    process_id,
                    user_id,
                    kind,
                    status,
                    started_at,
                    updated_at,
                    heartbeat_at,
                    current_job_id,
                    next_event_seq
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "process-1",
                    "user-1",
                    "action",
                    "completed",
                    "2026-03-24T00:00:00Z",
                    "2026-03-24T00:00:00Z",
                    "2026-03-24T00:00:00Z",
                    "job-1",
                    1,
                ),
            )
            connection.execute(
                """
                INSERT INTO jobs(
                    job_id,
                    user_id,
                    job_type,
                    process_id,
                    status,
                    scheduled_at,
                    completed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "job-1",
                    "user-1",
                    "execute_action",
                    "process-1",
                    "completed",
                    "2026-03-24T00:00:00Z",
                    "2026-03-24T00:10:00Z",
                ),
            )
            connection.execute(
                """
                INSERT INTO job_attempts(
                    attempt_id,
                    job_id,
                    attempt_number,
                    started_at,
                    status
                ) VALUES (?, ?, 1, '2026-03-24T00:00:00Z', 'running')
                """,
                ("attempt-1", "job-1"),
            )
            connection.execute(
                """
                INSERT INTO agent_suggestions(
                    suggestion_id,
                    user_id,
                    status,
                    created_at,
                    updated_at
                ) VALUES (?, ?, 'processing', '2026-03-24T00:00:00Z', '2026-03-24T00:00:00Z')
                """,
                ("synthetic-suggestion:action-1", "user-1"),
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
                ) VALUES (?, ?, ?, 'processing', '', 'local_runtime/tooling', 'synthetic', '2026-03-24T00:00:00Z', '2026-03-24T00:00:00Z')
                """,
                ("action-1", "user-1", "synthetic-suggestion:action-1"),
            )
            connection.execute(
                """
                INSERT INTO agent_action_steps(
                    step_id,
                    action_id,
                    user_id,
                    step_number,
                    local_step_number,
                    short_step_id,
                    step_type,
                    step_name,
                    status,
                    created_at
                ) VALUES (?, ?, ?, 1, 1, 'synthetic-1-TOOL', 'tool_execution', 'tool invocation', 'queued', '2026-03-24T00:00:00Z')
                """,
                ("step-1", "action-1", "user-1"),
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
                ) VALUES (?, ?, 'scratch', NULL, ?, NULL, 'none', '{}', 'app_managed', '{}', '2026-03-24T00:00:00Z', '2026-03-24T00:00:00Z')
                """,
                ("workspace-1", "user-1", str(tmp_path / "workspace-1")),
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
                ) VALUES (?, ?, ?, NULL, ?, 'brokered_file_ops', '.', NULL, NULL, 'cloud-proxy-only', '{}', '[]', 'running', '2026-03-24T00:00:00Z', NULL, NULL)
                """,
                ("session-1", "user-1", "action-1", "workspace-1"),
            )
            connection.execute(
                """
                INSERT INTO tool_definitions(
                    tool_id,
                    tool_name,
                    tool_description,
                    category,
                    risk_level,
                    input_schema_json,
                    output_schema_json,
                    rate_limit_json,
                    is_enabled,
                    version,
                    created_at,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, '{}', NULL, NULL, 1, '1', '2026-03-24T00:00:00Z', '2026-03-24T00:00:00Z')
                """,
                ("apply_patch", "Apply Patch", "Apply patch", "editor", "medium"),
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
                    tool_request_id,
                    status,
                    started_at,
                    completed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "invoke-1",
                    "user-1",
                    "action-1",
                    "step-1",
                    "apply_patch",
                    "workspace-1",
                    "session-1",
                    ".",
                    5000,
                    "surgical_edit",
                    "cloud-proxy-only",
                    "apply patch",
                    "{}",
                    "request-1",
                    "completed",
                    "2026-03-24T00:00:01Z",
                    "2026-03-24T00:00:02Z",
                ),
            )

    apply_migrations(
        db_path=db_path,
        busy_timeout_ms=1_000,
        migrations=_migrations_through(
            migrations,
            ACTION_TERMINAL_RUNTIME_REPAIRS_MIGRATION_NAME,
        ),
    )

    with sqlite3.connect(db_path) as connection:
        _configure_connection(connection, busy_timeout_ms=1_000)
        process_row = connection.execute(
            """
            SELECT completed_at, current_job_id
            FROM processes
            WHERE process_id = 'process-1'
            """
        ).fetchone()
        attempt_row = connection.execute(
            """
            SELECT status, completed_at, error_code
            FROM job_attempts
            WHERE attempt_id = 'attempt-1'
            """
        ).fetchone()
        step_row = connection.execute(
            """
            SELECT status, started_at, completed_at
            FROM agent_action_steps
            WHERE step_id = 'step-1'
            """
        ).fetchone()

    assert process_row == ("2026-03-24T00:10:00Z", None)
    assert attempt_row == (
        "completed",
        "2026-03-24T00:10:00Z",
        None,
    )
    assert step_row == (
        "success",
        "2026-03-24T00:00:01Z",
        "2026-03-24T00:00:02Z",
    )


def test_apply_migration_0033_drops_feature_readiness_table(tmp_path: Path) -> None:
    db_path = tmp_path / "runtime.db"
    migrations = load_default_migrations()
    migrations_through_v32 = _migrations_through(
        migrations,
        ACTION_TERMINAL_RUNTIME_REPAIRS_MIGRATION_NAME,
    )
    apply_migrations(
        db_path=db_path,
        busy_timeout_ms=1_000,
        migrations=migrations_through_v32,
    )

    with sqlite3.connect(db_path) as connection:
        feature_row = connection.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table'
              AND name = 'feature_readiness'
            """
        ).fetchone()

    assert feature_row is not None

    apply_migrations(
        db_path=db_path,
        busy_timeout_ms=1_000,
        migrations=migrations,
    )

    with sqlite3.connect(db_path) as connection:
        feature_row = connection.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table'
              AND name = 'feature_readiness'
            """
        ).fetchone()
        schema_row = connection.execute(
            """
            SELECT current_version, migration_name
            FROM schema_versions
            WHERE component = 'local_runtime'
            """
        ).fetchone()

    assert feature_row is None
    assert schema_row == (
        LATEST_LOCAL_RUNTIME_SCHEMA_VERSION,
        LATEST_LOCAL_RUNTIME_MIGRATION_NAME,
    )


def test_apply_migration_0030_allows_command_audit_without_approval_session(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "runtime.db"
    apply_migrations(
        db_path=db_path,
        busy_timeout_ms=1_000,
        migrations=load_default_migrations(),
    )

    with sqlite3.connect(db_path) as connection:
        _configure_connection(connection, busy_timeout_ms=1_000)
        table_sql = connection.execute(
            """
            SELECT sql
            FROM sqlite_master
            WHERE type = 'table'
              AND name = 'command_invocation_audits'
            """
        ).fetchone()

    assert table_sql is not None
    assert "approval_session_id TEXT NOT NULL" not in str(table_sql[0])
    assert "approval_session_id TEXT" in str(table_sql[0])


def test_insight_activity_summary_provenance_migration_preserves_legacy_rows(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "runtime.db"
    migrations = load_default_migrations()
    migration_name = "0078_insight_activity_summary_provenance.sql"
    apply_migrations(
        db_path=db_path,
        busy_timeout_ms=1_000,
        migrations=_migrations_before(migrations, migration_name),
    )
    with sqlite3.connect(db_path) as connection:
        _configure_connection(connection, busy_timeout_ms=1_000)
        with connection:
            _insert_user(connection, "user-1")
            connection.execute(
                """
                INSERT INTO agent_suggestions(
                    suggestion_id, user_id, status, answer, prompt_text,
                    response_text, prompt_name, prompt_version, has_suggestion,
                    interaction_contract, created_at, updated_at
                ) VALUES (
                    'suggestion-1', 'user-1', 'success', 'answer', 'prompt',
                    'response', 'suggestion', '1.0', 1, 'action_offer',
                    '2026-08-14T00:00:00Z', '2026-08-14T00:00:00Z'
                )
                """
            )
            connection.execute(
                """
                INSERT INTO agent_insights(
                    insight_id, user_id, suggestion_id, status,
                    short_term_insight_data, facts, prompt_name, prompt_version,
                    created_at, updated_at
                ) VALUES (
                    'insight-legacy', 'user-1', 'suggestion-1', 'success',
                    'legacy body', 'legacy facts', 'insight', '1.0',
                    '2026-08-14T00:00:00Z', '2026-08-14T00:00:00Z'
                )
                """
            )

    apply_migrations(
        db_path=db_path,
        busy_timeout_ms=1_000,
        migrations=migrations,
    )

    with sqlite3.connect(db_path) as connection:
        columns = {
            str(row[1]): int(row[3])
            for row in connection.execute("PRAGMA table_info(agent_insights)")
        }
        row = connection.execute(
            """
            SELECT suggestion_id, source_activity_summary_id,
                   short_term_insight_data, facts
            FROM agent_insights
            WHERE insight_id = 'insight-legacy'
            """
        ).fetchone()
        fts_row = connection.execute(
            """
            SELECT short_term_insight_data
            FROM memory_search_agent_insights_fts
            WHERE memory_search_agent_insights_fts MATCH 'legacy'
            """
        ).fetchone()
        foreign_key_violations = connection.execute(
            "PRAGMA foreign_key_check"
        ).fetchall()
        source_index_sql = connection.execute(
            """
            SELECT sql
            FROM sqlite_master
            WHERE type = 'index'
              AND name = 'idx_agent_insights_user_source_activity_summary'
            """
        ).fetchone()

    assert columns["suggestion_id"] == 0
    assert columns["source_activity_summary_id"] == 0
    assert row == ("suggestion-1", None, "legacy body", "legacy facts")
    assert fts_row == ("legacy body",)
    assert foreign_key_violations == []
    assert source_index_sql is not None
    assert "status = 'success'" in str(source_index_sql[0])
