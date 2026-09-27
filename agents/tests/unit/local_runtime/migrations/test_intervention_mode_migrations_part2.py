from __future__ import annotations

import sqlite3
from pathlib import Path

from pantaray_agents.local_runtime.storage.migrations.action_history_schema import (
    create_agent_suggestions_table,
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


def test_apply_migration_0028_recovers_partial_legacy_v28_state(
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
            _insert_user(connection, "user-1")
            connection.execute(
                "ALTER TABLE agent_suggestions ADD COLUMN intervention_mode TEXT"
            )
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
                "ALTER TABLE agent_suggestions RENAME TO agent_suggestions_legacy_v28"
            )
            create_agent_suggestions_table(connection)
            connection.execute("DROP TABLE agent_suggestion_history")
            connection.execute(
                """
                CREATE TABLE agent_suggestion_history (
                    suggestion_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    suggestion_created_at TEXT NOT NULL,
                    suggestion_updated_at TEXT NOT NULL,
                    suggestion_status TEXT NOT NULL CHECK (
                        suggestion_status IN ('processing', 'success', 'error', 'timeout', 'canceled')
                    ),
                    has_suggestion INTEGER NOT NULL CHECK (has_suggestion IN (0, 1)),
                    answer TEXT NOT NULL,
                    interaction_contract TEXT CHECK (
                        interaction_contract IS NULL
                        OR interaction_contract IN ('action_offer', 'message_only')
                    ),
                    intervention_mode TEXT CHECK (
                        intervention_mode IS NULL
                        OR intervention_mode IN ('Executor', 'Mirror', 'Challenger', 'Editor', 'Witness')
                    ),
                    user_reaction TEXT CHECK (
                        user_reaction IS NULL OR user_reaction IN ('accepted', 'rejected')
                    ),
                    accepted_at TEXT,
                    rejected_at TEXT,
                    action_status TEXT CHECK (
                        action_status IS NULL
                        OR action_status IN (
                            'idle',
                            'processing',
                            'success',
                            'error',
                            'canceled'
                        )
                    ),
                    action_failure_code TEXT,
                    action_failure_stage TEXT,
                    action_failure_message_public TEXT,
                    action_request_payload_present INTEGER NOT NULL DEFAULT 0 CHECK (
                        action_request_payload_present IN (0, 1)
                    ),
                    action_id TEXT,
                    action_created_at TEXT,
                    action_updated_at TEXT,
                    final_output TEXT,
                    last_sequence INTEGER NOT NULL DEFAULT 0 CHECK (last_sequence >= 0),
                    CHECK (interaction_contract <> 'message_only' OR user_reaction IS NULL),
                    CHECK (
                        (has_suggestion = 1 AND interaction_contract IS NOT NULL AND intervention_mode IS NOT NULL)
                        OR (has_suggestion = 0 AND interaction_contract IS NULL AND intervention_mode IS NULL)
                    ),
                    FOREIGN KEY (suggestion_id) REFERENCES agent_suggestions_legacy_v28(suggestion_id) ON DELETE CASCADE,
                    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
                    FOREIGN KEY (action_id) REFERENCES agent_actions(action_id) ON DELETE SET NULL
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
                    intervention_mode,
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
                    'Executor',
                    0,
                    'action-1',
                    '2026-03-24T00:00:01Z',
                    '2026-03-24T00:00:01Z',
                    'done',
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
        suggestion_row = connection.execute(
            """
            SELECT suggestion_id, has_suggestion, interaction_contract
            FROM agent_suggestions
            WHERE suggestion_id = 'suggestion-1'
            """
        ).fetchone()
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
        history_row = connection.execute(
            """
            SELECT suggestion_id, has_suggestion, interaction_contract
            FROM agent_suggestion_history
            WHERE suggestion_id = 'suggestion-1'
            """
        ).fetchone()
        history_columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(agent_suggestion_history)")
        }
        history_fk_rows = connection.execute(
            "PRAGMA foreign_key_list(agent_suggestion_history)"
        ).fetchall()
        event_fk_rows = connection.execute(
            "PRAGMA foreign_key_list(agent_process_events)"
        ).fetchall()
        fk_check_rows = connection.execute("PRAGMA foreign_key_check").fetchall()
        legacy_table_row = connection.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table' AND name = 'agent_suggestions_legacy_v28'
            """
        ).fetchone()

    assert suggestion_row == ("suggestion-1", 1, "action_offer")
    assert action_row == ("action-1", "suggestion-1")
    assert event_row == ("event-1", "suggestion-1")
    assert history_row == ("suggestion-1", 1, "action_offer")
    assert "intervention_mode" not in history_columns
    assert all("__rebuild_v16" not in str(row[2]) for row in history_fk_rows)
    assert all("__rebuild_v16" not in str(row[2]) for row in event_fk_rows)
    assert fk_check_rows == []
    assert legacy_table_row is None
