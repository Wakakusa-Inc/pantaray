from __future__ import annotations

import sqlite3
from pathlib import Path

from .support import (
    REMOVE_INTERVENTION_MODE_MIGRATION_NAME,
    _configure_connection,
    _insert_user,
    _migrations_before,
    _migrations_through,
    apply_migrations,
    load_default_migrations,
)


def test_apply_migration_0028_rebuilds_history_when_only_suggestions_need_upgrade(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "runtime.db"
    migrations = load_default_migrations()
    migrations_before_v28 = _migrations_before(
        migrations,
        REMOVE_INTERVENTION_MODE_MIGRATION_NAME,
    )
    migrations_through_v28 = _migrations_through(
        migrations,
        REMOVE_INTERVENTION_MODE_MIGRATION_NAME,
    )
    schema_migration = migrations_before_v28[-1]
    apply_migrations(
        db_path=db_path,
        busy_timeout_ms=1_000,
        migrations=migrations_before_v28,
    )

    with sqlite3.connect(db_path) as connection:
        _configure_connection(connection, busy_timeout_ms=1_000)
        with connection:
            connection.execute(
                "ALTER TABLE agent_suggestions ADD COLUMN intervention_mode TEXT"
            )
            _insert_user(connection, "user-1")
            connection.execute(
                """
                INSERT INTO agent_suggestions(
                    suggestion_id,
                    user_id,
                    status,
                    answer,
                    prompt_name,
                    prompt_version,
                    has_suggestion,
                    interaction_contract,
                    intervention_mode,
                    created_at,
                    updated_at
                ) VALUES (
                    'suggestion-1',
                    'user-1',
                    'success',
                    'answer',
                    'suggestion',
                    '1.0',
                    1,
                    'action_offer',
                    'Executor',
                    '2026-03-24T00:00:00Z',
                    '2026-03-24T00:00:00Z'
                )
                """
            )
            connection.execute(
                """
                INSERT INTO agent_suggestion_history(
                    suggestion_id,
                    user_id,
                    suggestion_created_at,
                    suggestion_updated_at,
                    suggestion_status,
                    has_suggestion,
                    answer,
                    interaction_contract,
                    user_reaction,
                    accepted_at,
                    rejected_at,
                    action_status,
                    action_failure_code,
                    action_failure_stage,
                    action_failure_message_public,
                    action_request_payload_present,
                    action_id,
                    action_created_at,
                    action_updated_at,
                    final_output,
                    last_sequence
                ) VALUES (
                    'suggestion-1',
                    'user-1',
                    '2026-03-24T00:00:00Z',
                    '2026-03-24T00:00:00Z',
                    'success',
                    1,
                    'answer',
                    'action_offer',
                    NULL,
                    NULL,
                    NULL,
                    NULL,
                    NULL,
                    NULL,
                    NULL,
                    0,
                    NULL,
                    NULL,
                    NULL,
                    NULL,
                    1
                )
                """
            )
            connection.execute(
                """
                UPDATE schema_versions
                SET
                    current_version = ?,
                    migration_name = ?,
                    checksum = ?
                WHERE component = 'local_runtime'
                """,
                (
                    schema_migration.version,
                    schema_migration.name,
                    schema_migration.checksum_sha256,
                ),
            )

    apply_migrations(
        db_path=db_path,
        busy_timeout_ms=1_000,
        migrations=migrations_through_v28,
    )

    with sqlite3.connect(db_path) as connection:
        _configure_connection(connection, busy_timeout_ms=1_000)
        history_fk_rows = connection.execute(
            "PRAGMA foreign_key_list(agent_suggestion_history)"
        ).fetchall()
        fk_check_rows = connection.execute("PRAGMA foreign_key_check").fetchall()
        remaining_row = connection.execute(
            """
            SELECT suggestion_id, has_suggestion, interaction_contract
            FROM agent_suggestion_history
            WHERE suggestion_id = 'suggestion-1'
            """
        ).fetchone()
        legacy_table_row = connection.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table' AND name = 'agent_suggestions_legacy_v28'
            """
        ).fetchone()

    assert any(str(row[2]) == "agent_suggestions" for row in history_fk_rows)
    assert all(str(row[2]) != "agent_suggestions_legacy_v28" for row in history_fk_rows)
    assert fk_check_rows == []
    assert remaining_row == ("suggestion-1", 1, "action_offer")
    assert legacy_table_row is None


def test_apply_migration_0028_rebuilds_all_suggestion_dependents_in_mixed_state(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "runtime.db"
    migrations = load_default_migrations()
    migrations_before_v28 = _migrations_before(
        migrations,
        REMOVE_INTERVENTION_MODE_MIGRATION_NAME,
    )
    migrations_through_v28 = _migrations_through(
        migrations,
        REMOVE_INTERVENTION_MODE_MIGRATION_NAME,
    )
    schema_migration = migrations_before_v28[-1]
    apply_migrations(
        db_path=db_path,
        busy_timeout_ms=1_000,
        migrations=migrations_before_v28,
    )

    with sqlite3.connect(db_path) as connection:
        _configure_connection(connection, busy_timeout_ms=1_000)
        with connection:
            connection.execute(
                "ALTER TABLE agent_suggestions ADD COLUMN intervention_mode TEXT"
            )
            _insert_user(connection, "user-1")
            connection.execute(
                """
                INSERT INTO agent_suggestions(
                    suggestion_id,
                    user_id,
                    status,
                    answer,
                    prompt_name,
                    prompt_version,
                    has_suggestion,
                    interaction_contract,
                    intervention_mode,
                    created_at,
                    updated_at
                ) VALUES (
                    'suggestion-1',
                    'user-1',
                    'success',
                    'answer',
                    'suggestion',
                    '1.0',
                    1,
                    'action_offer',
                    'Executor',
                    '2026-03-24T00:00:00Z',
                    '2026-03-24T00:00:00Z'
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
                    'success',
                    'done',
                    'action/executing',
                    '1.0',
                    '2026-03-24T00:00:01Z',
                    '2026-03-24T00:00:01Z'
                )
                """
            )
            connection.execute(
                """
                INSERT INTO agent_process_events(
                    event_id,
                    suggestion_id,
                    user_id,
                    action_id,
                    sequence,
                    event_name,
                    payload,
                    created_at
                ) VALUES (
                    'event-1',
                    'suggestion-1',
                    'user-1',
                    'action-1',
                    1,
                    'process_started',
                    '{"kind":"process_started"}',
                    '2026-03-24T00:00:02Z'
                )
                """
            )
            connection.execute(
                """
                UPDATE schema_versions
                SET
                    current_version = ?,
                    migration_name = ?,
                    checksum = ?
                WHERE component = 'local_runtime'
                """,
                (
                    schema_migration.version,
                    schema_migration.name,
                    schema_migration.checksum_sha256,
                ),
            )

    apply_migrations(
        db_path=db_path,
        busy_timeout_ms=1_000,
        migrations=migrations_through_v28,
    )

    with sqlite3.connect(db_path) as connection:
        _configure_connection(connection, busy_timeout_ms=1_000)
        action_fk_rows = connection.execute(
            "PRAGMA foreign_key_list(agent_actions)"
        ).fetchall()
        event_fk_rows = connection.execute(
            "PRAGMA foreign_key_list(agent_process_events)"
        ).fetchall()
        history_fk_rows = connection.execute(
            "PRAGMA foreign_key_list(agent_suggestion_history)"
        ).fetchall()
        fk_check_rows = connection.execute("PRAGMA foreign_key_check").fetchall()
        action_row = connection.execute(
            """
            SELECT action_id, suggestion_id
            FROM agent_actions
            WHERE action_id = 'action-1'
            """
        ).fetchone()
        event_row = connection.execute(
            """
            SELECT event_id, suggestion_id
            FROM agent_process_events
            WHERE event_id = 'event-1'
            """
        ).fetchone()
        legacy_table_row = connection.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table' AND name = 'agent_suggestions_legacy_v28'
            """
        ).fetchone()

    assert any(str(row[2]) == "agent_suggestions" for row in action_fk_rows)
    assert any(str(row[2]) == "agent_suggestions" for row in event_fk_rows)
    assert any(str(row[2]) == "agent_suggestions" for row in history_fk_rows)
    assert all(str(row[2]) != "agent_suggestions_legacy_v28" for row in action_fk_rows)
    assert all(str(row[2]) != "agent_suggestions_legacy_v28" for row in event_fk_rows)
    assert all(str(row[2]) != "agent_suggestions_legacy_v28" for row in history_fk_rows)
    assert fk_check_rows == []
    assert action_row == ("action-1", "suggestion-1")
    assert event_row == ("event-1", "suggestion-1")
    assert legacy_table_row is None
