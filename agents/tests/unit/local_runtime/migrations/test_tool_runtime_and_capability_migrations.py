from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from .support import (
    LATEST_LOCAL_RUNTIME_SCHEMA_VERSION,
    _insert_user,
    apply_migrations,
    load_default_migrations,
)


def test_apply_migrations_supports_composite_foreign_key_parents_for_insights(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "runtime.db"

    apply_migrations(
        db_path=db_path,
        busy_timeout_ms=1_000,
        migrations=load_default_migrations(),
    )

    with sqlite3.connect(db_path) as connection:
        with connection:
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
                    "2026-03-23T00:00:00Z",
                ),
            )
            connection.execute(
                """
                INSERT INTO agent_actions(
                    action_id,
                    user_id,
                    suggestion_id,
                    initial_user_message_id,
                    status,
                    execution_target_json,
                    final_output,
                    prompt_name,
                    prompt_version,
                    created_at,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "action-1",
                    "user-1",
                    "suggestion-1",
                    "message-action-1",
                    "processing",
                    '{"kind":"scratch"}',
                    "",
                    "action/executing",
                    "1.0",
                    "2026-03-23T00:00:00Z",
                    "2026-03-23T00:00:00Z",
                ),
            )
            connection.execute(
                """
                INSERT INTO agent_insights(
                    insight_id,
                    user_id,
                    suggestion_id,
                    action_id,
                    status,
                    short_term_insight_data,
                    facts,
                    prompt_name,
                    prompt_version
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "insight-1",
                    "user-1",
                    "suggestion-1",
                    "action-1",
                    "processing",
                    "short term",
                    "facts",
                    "prompt",
                    "v1",
                ),
            )


def test_apply_migrations_creates_tool_runtime_resource_event_tables(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "runtime.db"

    apply_migrations(
        db_path=db_path,
        busy_timeout_ms=1_000,
        migrations=load_default_migrations(),
    )

    with sqlite3.connect(db_path) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }

    assert "tool_runtime_resources" in tables
    assert "tool_runtime_resource_events" in tables
    assert "runtime_lock_resources" in tables
    assert "runtime_lock_events" in tables


def test_apply_migrations_rejects_socket_tool_runtime_resources(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "runtime.db"

    apply_migrations(
        db_path=db_path,
        busy_timeout_ms=1_000,
        migrations=load_default_migrations(),
    )

    with sqlite3.connect(db_path) as connection:
        with pytest.raises(
            sqlite3.IntegrityError,
            match="socket resources are outside the current local runtime transport scope",
        ):
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
                    'socket-resource-1',
                    'execution-session-1',
                    NULL,
                    'action-1',
                    'socket',
                    'active',
                    NULL,
                    NULL,
                    NULL,
                    '/tmp/socket',
                    '2026-03-23T00:00:00Z',
                    '2026-03-23T00:00:00Z',
                    NULL,
                    NULL,
                    0
                )
                """
            )


def test_apply_migrations_drops_legacy_capability_grants_without_preference_id(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "runtime.db"

    apply_migrations(
        db_path=db_path,
        busy_timeout_ms=1_000,
        migrations=load_default_migrations()[:8],
    )

    with sqlite3.connect(db_path) as connection:
        with connection:
            _insert_user(connection, "user-1")
            connection.execute(
                """
                INSERT INTO capability_grants(
                    grant_id,
                    user_id,
                    preference_id,
                    capability,
                    scope_type,
                    scope_ref,
                    grant_source,
                    granted_at,
                    granted_by,
                    revoked_at,
                    revocation_reason
                ) VALUES (
                    'grant-1',
                    'user-1',
                    NULL,
                    'scoped_write',
                    'global',
                    NULL,
                    'settings',
                    '2026-03-23T00:00:01Z',
                    'user',
                    NULL,
                    NULL
                )
                """
            )

    apply_migrations(
        db_path=db_path,
        busy_timeout_ms=1_000,
        migrations=load_default_migrations(),
    )

    with sqlite3.connect(db_path) as connection:
        row = connection.execute("SELECT COUNT(*) FROM capability_grants").fetchone()

    assert row == (0,)


def test_apply_migrations_recovers_from_partial_tooling_contract_column_addition(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "runtime.db"

    apply_migrations(
        db_path=db_path,
        busy_timeout_ms=1_000,
        migrations=load_default_migrations()[:8],
    )
    apply_migrations(
        db_path=db_path,
        busy_timeout_ms=1_000,
        migrations=load_default_migrations(),
    )

    with sqlite3.connect(db_path) as connection:
        execution_session_columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(execution_sessions)")
        }
        table_names = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        version_row = connection.execute(
            """
            SELECT current_version
            FROM schema_versions
            WHERE component = 'local_runtime'
            """
        ).fetchone()

    assert "workspaces" not in table_names
    assert "network_policy" in execution_session_columns
    assert version_row is not None
    assert int(version_row[0]) == LATEST_LOCAL_RUNTIME_SCHEMA_VERSION
