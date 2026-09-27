from __future__ import annotations

import sqlite3
from pathlib import Path

from .support import (
    _insert_user,
    apply_migrations,
    load_default_migrations,
)


def test_apply_migrations_aligns_legacy_public_projection_tables(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "runtime.db"
    apply_migrations(
        db_path=db_path,
        busy_timeout_ms=1_000,
        migrations=load_default_migrations()[:14],
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
                    action_request_payload,
                    created_at,
                    updated_at
                ) VALUES (
                    'suggestion-1',
                    'user-1',
                    'success',
                    'legacy answer',
                    'prompt',
                    'response',
                    'suggestion/meta_reasoning',
                    '1.0',
                    1,
                    'action_offer',
                    'Executor',
                    '{}',
                    '2026-03-23T00:00:00Z',
                    '2026-03-23T00:00:01Z'
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
                    'legacy final output',
                    'action/executing',
                    '1.0',
                    '2026-03-23T00:00:02Z',
                    '2026-03-23T00:00:03Z'
                )
                """
            )
            connection.execute(
                """
                UPDATE agent_suggestions
                SET action_execution_id = 'action-1',
                    action_command_id = 'command-1'
                WHERE suggestion_id = 'suggestion-1'
                """
            )
            connection.execute("DROP TABLE agent_process_events")
            connection.execute("DROP TABLE agent_suggestion_history")
            connection.execute(
                """
                CREATE TABLE agent_process_events (
                    process_event_id TEXT PRIMARY KEY,
                    process_id TEXT NOT NULL,
                    event_name TEXT NOT NULL,
                    payload_json TEXT NOT NULL CHECK (json_valid(payload_json)),
                    created_at TEXT NOT NULL,
                    suggestion_id TEXT,
                    user_id TEXT,
                    action_id TEXT,
                    sequence INTEGER
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE agent_suggestion_history (
                    history_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    suggestion_id TEXT NOT NULL,
                    action_id TEXT,
                    status TEXT NOT NULL,
                    answer TEXT,
                    interaction_contract TEXT,
                    intervention_mode TEXT,
                    user_reaction TEXT,
                    accepted_at TEXT,
                    rejected_at TEXT,
                    action_status TEXT,
                    action_failure_code TEXT,
                    action_failure_stage TEXT,
                    action_failure_message_public TEXT,
                    final_output TEXT,
                    action_updated_at TEXT,
                    suggestion_updated_at TEXT,
                    last_sequence INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT,
                    created_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                INSERT INTO agent_process_events(
                    process_event_id,
                    process_id,
                    event_name,
                    payload_json,
                    created_at,
                    suggestion_id,
                    user_id,
                    action_id,
                    sequence
                ) VALUES (
                    'event-1',
                    'process-1',
                    'process_completed',
                    '{"data":{"kind":"action","status":"success","final_output":"legacy final output","action_id":"action-1"}}',
                    '2026-03-23T00:00:03Z',
                    'suggestion-1',
                    'user-1',
                    'action-1',
                    1
                )
                """
            )
            connection.execute(
                """
                INSERT INTO agent_suggestion_history(
                    history_id,
                    user_id,
                    suggestion_id,
                    action_id,
                    status,
                    answer,
                    interaction_contract,
                    intervention_mode,
                    action_status,
                    final_output,
                    action_updated_at,
                    suggestion_updated_at,
                    last_sequence,
                    updated_at,
                    created_at
                ) VALUES (
                    'user-1:suggestion-1',
                    'user-1',
                    'suggestion-1',
                    'action-1',
                    'success',
                    'legacy answer',
                    'action_offer',
                    'Executor',
                    'success',
                    'legacy final output',
                    '2026-03-23T00:00:03Z',
                    '2026-03-23T00:00:03Z',
                    1,
                    '2026-03-23T00:00:03Z',
                    '2026-03-23T00:00:00Z'
                )
                """
            )

    apply_migrations(
        db_path=db_path,
        busy_timeout_ms=1_000,
        migrations=load_default_migrations(),
    )

    with sqlite3.connect(db_path) as connection:
        event_columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(agent_process_events)")
        }
        history_columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(agent_suggestion_history)")
        }
        event_row = connection.execute(
            """
            SELECT event_id, suggestion_id, user_id, action_id, sequence, payload
            FROM agent_process_events
            WHERE event_id = 'event-1'
            """
        ).fetchone()
        history_row = connection.execute(
            """
            SELECT
                suggestion_id,
                suggestion_status,
                has_suggestion,
                action_request_payload_present,
                final_output,
                last_sequence
            FROM agent_suggestion_history
            WHERE suggestion_id = 'suggestion-1'
            """
        ).fetchone()

    assert "event_id" in event_columns
    assert "payload" in event_columns
    assert "suggestion_status" in history_columns
    assert "action_request_payload_present" in history_columns
    assert event_row == (
        "event-1",
        "suggestion-1",
        "user-1",
        "action-1",
        1,
        '{"data":{"kind":"action","status":"success","final_output":"legacy final output","action_id":"action-1"}}',
    )
    assert history_row == (
        "suggestion-1",
        "success",
        1,
        1,
        "legacy final output",
        1,
    )


def test_apply_migrations_normalizes_legacy_retry_required_public_event(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "runtime.db"
    apply_migrations(
        db_path=db_path,
        busy_timeout_ms=1_000,
        migrations=load_default_migrations()[:14],
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
                    action_request_payload,
                    created_at,
                    updated_at
                ) VALUES (
                    'suggestion-1',
                    'user-1',
                    'success',
                    'legacy answer',
                    'prompt',
                    'response',
                    'suggestion/meta_reasoning',
                    '1.0',
                    1,
                    'action_offer',
                    'Executor',
                    '{}',
                    '2026-03-23T00:00:00Z',
                    '2026-03-23T00:00:01Z'
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
                    'legacy final output',
                    'action/executing',
                    '1.0',
                    '2026-03-23T00:00:02Z',
                    '2026-03-23T00:00:03Z'
                )
                """
            )
            connection.execute(
                """
                UPDATE agent_suggestions
                SET action_execution_id = 'action-1',
                    action_command_id = 'command-1'
                WHERE suggestion_id = 'suggestion-1'
                """
            )
            connection.execute("DROP TABLE agent_process_events")
            connection.execute("DROP TABLE agent_suggestion_history")
            connection.execute(
                """
                CREATE TABLE agent_process_events (
                    process_event_id TEXT PRIMARY KEY,
                    process_id TEXT NOT NULL,
                    event_name TEXT NOT NULL,
                    payload_json TEXT NOT NULL CHECK (json_valid(payload_json)),
                    created_at TEXT NOT NULL,
                    suggestion_id TEXT,
                    user_id TEXT,
                    action_id TEXT,
                    sequence INTEGER
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE agent_suggestion_history (
                    history_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    suggestion_id TEXT NOT NULL,
                    action_id TEXT,
                    status TEXT NOT NULL,
                    answer TEXT,
                    interaction_contract TEXT,
                    intervention_mode TEXT,
                    user_reaction TEXT,
                    accepted_at TEXT,
                    rejected_at TEXT,
                    action_status TEXT,
                    action_failure_code TEXT,
                    action_failure_stage TEXT,
                    action_failure_message_public TEXT,
                    final_output TEXT,
                    action_updated_at TEXT,
                    suggestion_updated_at TEXT,
                    last_sequence INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT,
                    created_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                INSERT INTO agent_process_events(
                    process_event_id,
                    process_id,
                    event_name,
                    payload_json,
                    created_at,
                    suggestion_id,
                    user_id,
                    action_id,
                    sequence
                ) VALUES (
                    'event-1',
                    'process-1',
                    'action_start_retry_required',
                    '{"data":{"kind":"action","failure_code":"ACTION_START_FAILED","failure_stage":"spawn","failure_message_public":"retry required","accepted_at":"2026-03-23T00:00:02Z","process_id":"process-1","action_id":"action-1","command_id":"command-1"}}',
                    '2026-03-23T00:00:03Z',
                    'suggestion-1',
                    'user-1',
                    'action-1',
                    1
                )
                """
            )
            connection.execute(
                """
                INSERT INTO agent_suggestion_history(
                    history_id,
                    user_id,
                    suggestion_id,
                    action_id,
                    status,
                    answer,
                    interaction_contract,
                    intervention_mode,
                    action_status,
                    action_failure_code,
                    action_failure_stage,
                    action_failure_message_public,
                    final_output,
                    action_updated_at,
                    suggestion_updated_at,
                    last_sequence,
                    updated_at,
                    created_at
                ) VALUES (
                    'user-1:suggestion-1',
                    'user-1',
                    'suggestion-1',
                    'action-1',
                    'success',
                    'legacy answer',
                    'action_offer',
                    'Executor',
                    'idle',
                    'ACTION_START_FAILED',
                    'spawn',
                    'retry required',
                    'legacy final output',
                    '2026-03-23T00:00:03Z',
                    '2026-03-23T00:00:03Z',
                    1,
                    '2026-03-23T00:00:03Z',
                    '2026-03-23T00:00:00Z'
                )
                """
            )

    apply_migrations(
        db_path=db_path,
        busy_timeout_ms=1_000,
        migrations=load_default_migrations(),
    )

    with sqlite3.connect(db_path) as connection:
        event_row = connection.execute(
            """
            SELECT event_name, payload
            FROM agent_process_events
            WHERE event_id = 'event-1'
            """
        ).fetchone()

    assert event_row == (
        "error",
        '{"data":{"kind":"action","failure_code":"ACTION_START_FAILED","failure_stage":"spawn","failure_message_public":"retry required","accepted_at":"2026-03-23T00:00:02Z","process_id":"process-1","action_id":"action-1","command_id":"command-1"}}',
    )
