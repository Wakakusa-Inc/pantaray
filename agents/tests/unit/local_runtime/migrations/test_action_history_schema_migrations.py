from __future__ import annotations

import sqlite3
from pathlib import Path

from .support import (
    _insert_user,
    apply_migrations,
    load_default_migrations,
)


def test_apply_migration_0007_aligns_legacy_action_history_tables(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "runtime.db"
    migrations = load_default_migrations()
    apply_migrations(
        db_path=db_path,
        busy_timeout_ms=1_000,
        migrations=migrations[:1],
    )

    with sqlite3.connect(db_path) as connection:
        with connection:
            _insert_user(connection, "user-1")
            connection.executescript(
                """
                CREATE TABLE agent_suggestions (
                    suggestion_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    answer TEXT,
                    error_json TEXT CHECK (error_json IS NULL OR json_valid(error_json)),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY (user_id) REFERENCES users(user_id)
                );
                CREATE TABLE agent_actions (
                    action_id TEXT PRIMARY KEY,
                    suggestion_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    command_json TEXT NOT NULL CHECK (json_valid(command_json)),
                    final_output TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY (suggestion_id) REFERENCES agent_suggestions(suggestion_id),
                    FOREIGN KEY (user_id) REFERENCES users(user_id)
                );
                CREATE TABLE agent_action_steps (
                    action_step_id TEXT PRIMARY KEY,
                    action_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    step_type TEXT NOT NULL,
                    local_step_number INTEGER NOT NULL CHECK (local_step_number >= 1),
                    payload_json TEXT NOT NULL CHECK (json_valid(payload_json)),
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (action_id) REFERENCES agent_actions(action_id),
                    FOREIGN KEY (user_id) REFERENCES users(user_id)
                );
                """
            )
            connection.execute(
                """
                INSERT INTO agent_suggestions(
                    suggestion_id,
                    user_id,
                    status,
                    answer,
                    error_json,
                    created_at,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "suggestion-1",
                    "user-1",
                    "success",
                    "legacy answer",
                    '{"type":"LegacyError"}',
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
                    command_json,
                    final_output,
                    created_at,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "action-1",
                    "suggestion-1",
                    "user-1",
                    "success",
                    '{"command":"legacy"}',
                    "legacy final output",
                    "2026-03-23T00:00:02Z",
                    "2026-03-23T00:00:03Z",
                ),
            )
            connection.execute(
                """
                INSERT INTO agent_action_steps(
                    action_step_id,
                    action_id,
                    user_id,
                    step_type,
                    local_step_number,
                    payload_json,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "legacy-step-1",
                    "action-1",
                    "user-1",
                    "tool_execution",
                    1,
                    '{"tool":"bash"}',
                    "2026-03-23T00:00:04Z",
                ),
            )
            connection.execute(
                """
                UPDATE schema_versions
                SET current_version = 6,
                    migration_name = '0006_scheduler_security.sql',
                    checksum = 'legacy-v6-test'
                WHERE component = 'local_runtime'
                """
            )

    apply_migrations(
        db_path=db_path,
        busy_timeout_ms=1_000,
        migrations=migrations[6:7],
    )

    with sqlite3.connect(db_path) as connection:
        suggestion_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(agent_suggestions)")
        }
        action_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(agent_actions)")
        }
        step_columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(agent_action_steps)")
        }
        migrated_suggestion = connection.execute(
            """
            SELECT prompt_name, prompt_version, has_suggestion, error
            FROM agent_suggestions
            WHERE suggestion_id = 'suggestion-1'
            """
        ).fetchone()
        migrated_action = connection.execute(
            """
            SELECT prompt_name, prompt_version, final_output
            FROM agent_actions
            WHERE action_id = 'action-1'
            """
        ).fetchone()
        migrated_step = connection.execute(
            """
            SELECT step_id, step_number, short_step_id, step_type, status
            FROM agent_action_steps
            WHERE step_id = 'legacy-step-1'
            """
        ).fetchone()

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
                "suggestion-2",
                "user-1",
                "processing",
                "2026-03-23T00:00:10Z",
                "2026-03-23T00:00:10Z",
            ),
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
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "action-2",
                "user-1",
                "suggestion-2",
                "processing",
                "",
                "action/executing",
                "1.0",
                "2026-03-23T00:00:11Z",
                "2026-03-23T00:00:11Z",
            ),
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
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "step-2",
                "action-2",
                "user-1",
                1,
                1,
                "synthetic-1-TOOL",
                "tool_execution",
                "tool invocation",
                "queued",
                "2026-03-23T00:00:12Z",
            ),
        )

    assert "action_status" in suggestion_columns
    assert "action_request_payload" in suggestion_columns
    assert "prompt_name" in action_columns
    assert "total_steps" in action_columns
    assert "step_id" in step_columns
    assert "step_number" in step_columns
    assert migrated_suggestion == (
        "legacy/local_runtime",
        "pre-v7",
        0,
        '{"type":"LegacyError"}',
    )
    assert migrated_action == (
        "legacy/local_runtime",
        "pre-v7",
        "legacy final output",
    )
    assert migrated_step == (
        "legacy-step-1",
        1,
        "legacy-1-MIGRATED",
        "tool_execution",
        "success",
    )


def test_apply_migration_0016_normalizes_legacy_action_statuses(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "runtime.db"
    migrations = load_default_migrations()
    apply_migrations(
        db_path=db_path,
        busy_timeout_ms=1_000,
        migrations=migrations[:15],
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
                    answer,
                    prompt_text,
                    response_text,
                    prompt_name,
                    prompt_version,
                    has_suggestion,
                    interaction_contract,
                    intervention_mode,
                    action_status,
                    created_at,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "suggestion-1",
                    "user-1",
                    "success",
                    "answer",
                    "prompt",
                    "response",
                    "suggestion/meta_reasoning",
                    "1.0",
                    1,
                    "action_offer",
                    "Executor",
                    "timeout",
                    "2026-03-23T00:00:00Z",
                    "2026-03-23T00:00:01Z",
                ),
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
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "action-1",
                    "user-1",
                    "suggestion-1",
                    "timeout",
                    "",
                    "action/executing",
                    "1.0",
                    "2026-03-23T00:00:00Z",
                    "2026-03-23T00:00:01Z",
                ),
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
                    action_status,
                    action_request_payload_present,
                    action_id,
                    action_created_at,
                    action_updated_at,
                    final_output,
                    last_sequence
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "suggestion-1",
                    "user-1",
                    "2026-03-23T00:00:00Z",
                    "2026-03-23T00:00:01Z",
                    "success",
                    1,
                    "answer",
                    "action_offer",
                    "Executor",
                    "abandoned",
                    0,
                    "action-1",
                    "2026-03-23T00:00:00Z",
                    "2026-03-23T00:00:01Z",
                    None,
                    1,
                ),
            )
            connection.execute(
                """
                INSERT INTO processes(
                    process_id,
                    user_id,
                    kind,
                    status,
                    suggestion_id,
                    action_id,
                    started_at,
                    updated_at,
                    completed_at,
                    heartbeat_at,
                    next_event_seq
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "process-1",
                    "user-1",
                    "action",
                    "timeout",
                    "suggestion-1",
                    "action-1",
                    "2026-03-23T00:00:00Z",
                    "2026-03-23T00:00:01Z",
                    "2026-03-23T00:00:02Z",
                    "2026-03-23T00:00:01Z",
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
                    scheduled_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    "job-1",
                    "user-1",
                    "execute_action",
                    "process-1",
                    "running",
                    "2026-03-23T00:00:00Z",
                ),
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
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "event-1",
                    "suggestion-1",
                    "user-1",
                    "action-1",
                    1,
                    "process_completed",
                    '{"data":{"kind":"action","status":"timeout"},"meta":{"kind":"action"}}',
                    "2026-03-23T00:00:02Z",
                ),
            )

    apply_migrations(
        db_path=db_path,
        busy_timeout_ms=1_000,
        migrations=migrations[:16],
    )

    with sqlite3.connect(db_path) as connection:
        suggestion_row = connection.execute(
            """
            SELECT action_status, action_failure_code, action_failure_stage
            FROM agent_suggestions
            WHERE suggestion_id = 'suggestion-1'
            """
        ).fetchone()
        action_row = connection.execute(
            "SELECT status FROM agent_actions WHERE action_id = 'action-1'"
        ).fetchone()
        history_row = connection.execute(
            """
            SELECT action_status, action_failure_code
            FROM agent_suggestion_history
            WHERE suggestion_id = 'suggestion-1'
            """
        ).fetchone()
        process_row = connection.execute(
            "SELECT status FROM processes WHERE process_id = 'process-1'"
        ).fetchone()
        event_row = connection.execute(
            "SELECT payload FROM agent_process_events WHERE event_id = 'event-1'"
        ).fetchone()
        referenced_legacy_tables = []
        for table_row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name ASC"
        ):
            table_name = str(table_row[0])
            foreign_keys = connection.execute(
                f"PRAGMA foreign_key_list('{table_name}')"
            ).fetchall()
            for foreign_key in foreign_keys:
                parent_table_name = str(foreign_key[2])
                if parent_table_name.endswith("_legacy_v16"):
                    referenced_legacy_tables.append((table_name, parent_table_name))
        lingering_legacy_tables = [
            str(row[0])
            for row in connection.execute(
                """
                SELECT name
                FROM sqlite_master
                WHERE type = 'table' AND name LIKE '%_legacy_v16'
                ORDER BY name ASC
                """
            ).fetchall()
        ]

    assert suggestion_row == ("error", "ACTION_PROCESSING_TIMEOUT", "running_failed")
    assert action_row == ("error",)
    assert history_row == ("error", "ACTION_PROCESSING_ERROR")
    assert process_row == ("failed",)
    assert event_row is not None
    assert '"status":"error"' in str(event_row[0])
    assert referenced_legacy_tables == []
    assert lingering_legacy_tables == []
