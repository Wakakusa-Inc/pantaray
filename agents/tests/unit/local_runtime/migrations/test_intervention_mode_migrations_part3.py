from __future__ import annotations

import sqlite3
from pathlib import Path

from pantaray_agents.local_runtime.storage.migrations.action_history_schema import (
    create_agent_actions_table,
)

from .support import (
    REMOVE_INTERVENTION_MODE_MIGRATION_NAME,
    _configure_connection,
    _insert_user,
    _migrations_before,
    _migrations_through,
    apply_migrations,
    load_default_migrations,
)


def test_apply_migration_0028_repairs_current_tables_with_stale_migration_references(
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
        migrations=migrations_through_v28,
    )

    with sqlite3.connect(db_path) as connection:
        _configure_connection(connection, busy_timeout_ms=1_000)
        with connection:
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
                INSERT INTO agent_suggestion_history(
                    suggestion_id,
                    user_id,
                    suggestion_created_at,
                    suggestion_updated_at,
                    suggestion_status,
                    has_suggestion,
                    answer,
                    interaction_contract,
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
                    0,
                    'action-1',
                    '2026-03-24T00:00:01Z',
                    '2026-03-24T00:00:01Z',
                    'done',
                    1
                )
                """
            )
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
            connection.execute(
                "ALTER TABLE agent_actions RENAME TO agent_actions__rebuild_v16"
            )
            create_agent_actions_table(connection)
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
                )
                SELECT
                    action_id,
                    user_id,
                    suggestion_id,
                    status,
                    final_output,
                    prompt_name,
                    prompt_version,
                    created_at,
                    updated_at
                FROM agent_actions__rebuild_v16
                """
            )
            for trigger_name, trigger_sql in trigger_rows:
                connection.execute(f'DROP TRIGGER IF EXISTS "{trigger_name}"')
                connection.execute(
                    str(trigger_sql).replace(
                        "agent_suggestions",
                        "agent_suggestions_legacy_v28",
                    )
                )
            connection.execute("DROP TABLE agent_actions__rebuild_v16")
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
        with connection:
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
                    created_at,
                    updated_at
                ) VALUES (
                    'suggestion-2',
                    'user-1',
                    'success',
                    'answer 2',
                    'suggestion',
                    '1.0',
                    1,
                    'action_offer',
                    '2026-03-24T00:01:00Z',
                    '2026-03-24T00:01:00Z'
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
                    'action-2',
                    'user-1',
                    'suggestion-2',
                    'success',
                    'done 2',
                    'action/executing',
                    '1.0',
                    '2026-03-24T00:01:01Z',
                    '2026-03-24T00:01:01Z'
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
                    action_request_payload_present,
                    action_id,
                    action_created_at,
                    action_updated_at,
                    final_output,
                    last_sequence
                ) VALUES (
                    'suggestion-2',
                    'user-1',
                    '2026-03-24T00:01:00Z',
                    '2026-03-24T00:01:00Z',
                    'success',
                    1,
                    'answer 2',
                    'action_offer',
                    0,
                    'action-2',
                    '2026-03-24T00:01:01Z',
                    '2026-03-24T00:01:01Z',
                    'done 2',
                    1
                )
                """
            )
        history_fk_rows = connection.execute(
            "PRAGMA foreign_key_list(agent_suggestion_history)"
        ).fetchall()
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
        fk_check_rows = connection.execute("PRAGMA foreign_key_check").fetchall()
        history_row = connection.execute(
            """
            SELECT suggestion_id, action_id
            FROM agent_suggestion_history
            WHERE suggestion_id = 'suggestion-1'
            """
        ).fetchone()

    assert any(str(row[2]) == "agent_actions" for row in history_fk_rows)
    assert all("__rebuild_v16" not in str(row[2]) for row in history_fk_rows)
    assert all(
        "agent_suggestions_legacy_v28" not in str(row[0]) for row in trigger_rows
    )
    assert fk_check_rows == []
    assert history_row == ("suggestion-1", None)
