from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable
from pathlib import Path

import pytest

from pantaray_agents.local_runtime.storage.migrations import MigrationError
from pantaray_agents.local_runtime.storage.migrations.connection import (
    configure_connection,
)

from .support import (
    _migrations_before,
    _migrations_through,
    apply_migrations,
    load_default_migrations,
)

BUSY_TIMEOUT_MS = 1_000
MIGRATION_NAME = "0082_action_creation_cutover.sql"
USER_ID = "user-1"
TIMESTAMP = "2026-08-16T00:00:00Z"


def _apply_before_v82(db_path: Path) -> None:
    apply_migrations(
        db_path,
        BUSY_TIMEOUT_MS,
        _migrations_before(load_default_migrations(), MIGRATION_NAME),
    )


def _apply_v82(db_path: Path) -> None:
    apply_migrations(
        db_path,
        BUSY_TIMEOUT_MS,
        _migrations_through(load_default_migrations(), MIGRATION_NAME),
    )


def _insert_user(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        INSERT INTO users(user_id, ui_language, created_at, updated_at)
        VALUES (?, 'ja', ?, ?)
        """,
        (USER_ID, TIMESTAMP, TIMESTAMP),
    )


def _insert_terminal_action(
    connection: sqlite3.Connection,
    *,
    action_id: str = "action-1",
    suggestion_id: str = "suggestion-1",
    command_id: str | None = "message-1",
    action_status: str = "success",
) -> None:
    connection.execute(
        """
        INSERT INTO agent_suggestions(
            suggestion_id, user_id, status, answer, prompt_name, prompt_version,
            has_suggestion, interaction_contract, user_reaction, accepted_at,
            action_status, action_execution_id, action_command_id,
            created_at, updated_at
        ) VALUES (?, ?, 'success', 'approved suggestion', 'suggestion', '1.0',
                  1, 'action_offer', 'accepted', ?, ?, ?, ?, ?, ?)
        """,
        (
            suggestion_id,
            USER_ID,
            TIMESTAMP,
            action_status,
            action_id,
            command_id,
            TIMESTAMP,
            TIMESTAMP,
        ),
    )
    connection.execute(
        """
        INSERT INTO agent_actions(
            action_id, user_id, suggestion_id, status, final_output, error,
            final_prompt_text, generation, steps_budget, llm_steps_budget,
            tool_steps_budget, token_budget, total_steps, total_llm_steps,
            total_tool_steps, total_prompt_tokens, total_completion_tokens,
            total_tokens, prompt_name, prompt_version, created_at, updated_at
        ) VALUES (?, ?, ?, ?, 'done', NULL, 'final prompt', 2, 30, 20, 10,
                  1000, 3, 1, 1, 20, 10, 30, 'action', '2.0', ?, ?)
        """,
        (action_id, USER_ID, suggestion_id, action_status, TIMESTAMP, TIMESTAMP),
    )


def _insert_terminal_history(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        INSERT INTO agent_action_steps(
            step_id, action_id, user_id, step_number, local_step_number,
            short_step_id, step_type, step_name, status, started_at,
            completed_at, goal_handle, user_request_text, runtime_state_checkpoint,
            runtime_state_checkpoint_version, created_at
        ) VALUES ('step-user', 'action-1', ?, 1, 1, 'S-1-USER',
                  'user_request', 'user request', 'success', ?, ?, 'S',
                  'approved suggestion', '{"legacy":true}', 1, ?)
        """,
        (USER_ID, TIMESTAMP, TIMESTAMP, TIMESTAMP),
    )
    connection.execute(
        """
        INSERT INTO agent_action_steps(
            step_id, action_id, user_id, parent_step_id, step_number,
            local_step_number, short_step_id, step_type, step_name, status,
            thinking, llm_prompt_text, llm_response_text, prompt_tokens,
            completion_tokens, created_at
        ) VALUES ('step-think', 'action-1', ?, 'step-user', 1, 1,
                  'S-1-THINK', 'llm_output', 'reasoning', 'success',
                  'thinking', 'prompt', 'response', 20, 10, ?)
        """,
        (USER_ID, TIMESTAMP),
    )
    connection.execute(
        """
        INSERT INTO agent_action_steps(
            step_id, action_id, user_id, parent_step_id, step_number,
            local_step_number, short_step_id, step_type, step_name, status,
            tool_args, tool_output, created_at
        ) VALUES ('step-tool', 'action-1', ?, 'step-think', 1, 1,
                  'S-1-TOOL', 'tool_execution', 'tool', 'success',
                  '{"path":"a.txt"}', '{"status":"success"}', ?)
        """,
        (USER_ID, TIMESTAMP),
    )
    connection.execute(
        """
        INSERT INTO agent_process_events(
            event_id, suggestion_id, user_id, action_id, sequence,
            event_name, payload, created_at
        ) VALUES ('public-event-1', 'suggestion-1', ?, 'action-1', 1,
                  'process_completed', '{"status":"success"}', ?)
        """,
        (USER_ID, TIMESTAMP),
    )


def _insert_terminal_job_audit(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        INSERT INTO processes(
            process_id, user_id, kind, status, suggestion_id, action_id,
            started_at, updated_at, completed_at, heartbeat_at, next_event_seq
        ) VALUES ('process-1', ?, 'action', 'completed', 'suggestion-1',
                  'action-1', ?, ?, ?, ?, 2)
        """,
        (USER_ID, TIMESTAMP, TIMESTAMP, TIMESTAMP, TIMESTAMP),
    )
    connection.execute(
        """
        INSERT INTO jobs(
            job_id, user_id, job_type, process_id, status, attempt,
            scheduled_at, started_at, completed_at, logical_key
        ) VALUES ('job-1', ?, 'execute_action', 'process-1', 'completed', 1,
                  ?, ?, ?, 'action-1')
        """,
        (USER_ID, TIMESTAMP, TIMESTAMP, TIMESTAMP),
    )
    connection.execute(
        """
        INSERT INTO job_attempts(
            attempt_id, job_id, attempt_number, started_at, completed_at, status
        ) VALUES ('attempt-1', 'job-1', 1, ?, ?, 'completed')
        """,
        (TIMESTAMP, TIMESTAMP),
    )
    connection.execute(
        """
        INSERT INTO job_payloads(job_id, payload_json, created_at)
        VALUES ('job-1', '{"legacy":"payload"}', ?)
        """,
        (TIMESTAMP,),
    )
    connection.execute(
        """
        INSERT INTO process_events(
            process_id, event_seq, event_id, event_name, payload_json, created_at
        ) VALUES ('process-1', 1, 'internal-event-1', 'completed',
                  '{"legacy":"audit"}', ?)
        """,
        (TIMESTAMP,),
    )


def _insert_terminal_tool_audit(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        INSERT INTO execution_sessions(
            execution_session_id, user_id, action_id, exec_mode, cwd_path,
            network_policy, capability_snapshot_json, status, started_at,
            completed_at
        ) VALUES ('session-terminal', ?, 'action-1', 'brokered_file_ops', '.',
                  'cloud-proxy-only', '{}', 'completed', ?, ?)
        """,
        (USER_ID, TIMESTAMP, TIMESTAMP),
    )
    connection.execute(
        """
        INSERT INTO workspace_manifests(
            manifest_id, user_id, action_id, execution_session_id,
            scratch_root_path, created_at, materialized_at, status
        ) VALUES ('manifest-terminal', ?, 'action-1', 'session-terminal',
                  '/tmp/action-1', ?, ?, 'ready')
        """,
        (USER_ID, TIMESTAMP, TIMESTAMP),
    )
    connection.execute(
        """
        INSERT INTO tool_definitions(
            tool_id, tool_name, tool_description, category, risk_level,
            input_schema_json, is_enabled, version, created_at, updated_at
        ) VALUES ('tool-terminal', 'Tool', 'Tool', 'editor', 'medium', '{}',
                  1, '1', ?, ?)
        """,
        (TIMESTAMP, TIMESTAMP),
    )
    connection.execute(
        """
        INSERT INTO tool_invocations(
            invocation_id, user_id, action_id, tool_id, manifest_id,
            execution_session_id, intent_class, started_at, completed_at,
            status
        ) VALUES ('invocation-terminal', ?, 'action-1', 'tool-terminal',
                  'manifest-terminal', 'session-terminal', 'surgical_edit',
                  ?, ?, 'completed')
        """,
        (USER_ID, TIMESTAMP, TIMESTAMP),
    )
    connection.execute(
        """
        INSERT INTO tool_outputs(
            output_id, invocation_id, output_json, output_storage_kind,
            redaction_applied, created_at
        ) VALUES ('output-terminal', 'invocation-terminal', '{"done":true}',
                  'inline_json', 0, ?)
        """,
        (TIMESTAMP,),
    )
    connection.execute(
        """
        INSERT INTO approval_sessions(
            approval_session_id, user_id, action_id, manifest_id,
            tool_request_id, tool_invocation_id, tool_id, intent_class,
            approval_source, status, approved_capabilities_json,
            command_summary_json, requested_at, decided_at, created_at,
            claimed_at
        ) VALUES ('approval-terminal', ?, 'action-1', 'manifest-terminal',
                  'request-terminal', 'invocation-terminal', 'tool-terminal',
                  'surgical_edit', 'prompt', 'approved_once', '[]', '{}',
                  ?, ?, ?, ?)
        """,
        (USER_ID, TIMESTAMP, TIMESTAMP, TIMESTAMP, TIMESTAMP),
    )
    connection.execute(
        """
        INSERT INTO tool_runtime_resources(
            resource_id, execution_session_id, tool_invocation_id, action_id,
            resource_kind, status, resource_path, created_at, updated_at,
            cleaned_at
        ) VALUES ('resource-terminal', 'session-terminal',
                  'invocation-terminal', 'action-1', 'temp_file', 'cleaned',
                  '/tmp/action-1/output.txt', ?, ?, ?)
        """,
        (TIMESTAMP, TIMESTAMP, TIMESTAMP),
    )
    connection.execute(
        """
        INSERT INTO file_references(
            file_reference_id, user_id, action_id, manifest_id,
            tool_invocation_id, local_path, canonical_local_path, created_at
        ) VALUES ('file-terminal', ?, 'action-1', 'manifest-terminal',
                  'invocation-terminal', 'output.txt',
                  '/tmp/action-1/output.txt', ?)
        """,
        (USER_ID, TIMESTAMP),
    )


def _load_terminal_tool_audit(
    connection: sqlite3.Connection,
) -> tuple[tuple[str | int | float | bytes | None, ...], ...]:
    tables = (
        "execution_sessions",
        "workspace_manifests",
        "tool_invocations",
        "tool_outputs",
        "approval_sessions",
        "tool_runtime_resources",
        "file_references",
    )
    return tuple(
        tuple(connection.execute(f"SELECT * FROM {table_name}").fetchone() or ())
        for table_name in tables
    )


def test_fresh_database_has_v82_action_creation_schema(tmp_path: Path) -> None:
    db_path = tmp_path / "runtime.db"
    _apply_v82(db_path)

    with sqlite3.connect(db_path) as connection:
        configure_connection(connection, BUSY_TIMEOUT_MS)
        action_columns = {
            str(row[1]): int(row[3])
            for row in connection.execute("PRAGMA table_info(agent_actions)")
        }
        event_columns = {
            str(row[1]): int(row[3])
            for row in connection.execute("PRAGMA table_info(agent_process_events)")
        }
        suggestion_columns = {
            str(row[1])
            for row in connection.execute("PRAGMA table_info(agent_suggestions)")
        }
        action_sql = str(
            connection.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name='agent_actions'"
            ).fetchone()[0]
        )
        indexes = {
            str(row[0]): str(row[1])
            for row in connection.execute(
                """
                SELECT name, sql FROM sqlite_master
                WHERE type='index' AND name LIKE 'uq_agent_%'
                """
            )
        }
        user_message_index_columns = [
            str(row[2])
            for row in connection.execute(
                "PRAGMA index_info('uq_agent_action_steps_user_message')"
            )
        ]
        _insert_user(connection)
        connection.execute(
            """
            INSERT INTO agent_actions(
                action_id, user_id, suggestion_id, initial_user_message_id,
                status, execution_target_json, final_output,
                prompt_name, prompt_version, created_at, updated_at
            ) VALUES ('standalone-action', ?, NULL, 'message-standalone',
                      'queued', '{"kind":"scratch"}', '', 'action', '1.0', ?, ?)
            """,
            (USER_ID, TIMESTAMP, TIMESTAMP),
        )
        connection.execute(
            """
            INSERT INTO agent_action_steps(
                step_id, action_id, user_id, step_number, local_step_number,
                short_step_id, step_type, step_name, status, user_request_text,
                user_message_id, user_message_json, created_at
            ) VALUES ('standalone-user', 'standalone-action', ?, 1, 1,
                      'S-1-USER', 'user_request', 'user request', 'success',
                      'hello', 'message-standalone', '{"text":"hello"}', ?)
            """,
            (USER_ID, TIMESTAMP),
        )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO agent_actions(
                    action_id, user_id, suggestion_id, initial_user_message_id,
                    status, execution_target_json, final_output,
                    prompt_name, prompt_version, created_at, updated_at
                ) VALUES ('duplicate-message-action', ?, NULL,
                          'message-standalone', 'queued', '{"kind":"scratch"}',
                          '', 'action', '1.0', ?, ?)
                """,
                (USER_ID, TIMESTAMP, TIMESTAMP),
            )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO agent_action_steps(
                    step_id, action_id, user_id, step_number, step_type,
                    step_name, status, user_request_text, user_message_id,
                    created_at
                ) VALUES ('invalid-user-v1', 'standalone-action', ?, 2,
                          'user_request', 'user request', 'success', 'hello',
                          'message-invalid', ?)
                """,
                (USER_ID, TIMESTAMP),
            )
        connection.executemany(
            """
            INSERT INTO jobs(
                job_id, user_id, job_type, status, scheduled_at, logical_key
            ) VALUES (?, ?, 'extract_agent_experience', 'completed', ?, ?)
            """,
            (
                ("experience-job-1", USER_ID, TIMESTAMP, "experience-job-1"),
                ("experience-job-2", USER_ID, TIMESTAMP, "experience-job-2"),
            ),
        )
        connection.executemany(
            """
            INSERT INTO agent_experience_extraction_runs(
                user_id, job_id, action_id, operation, prompt_name,
                prompt_version, completed_at
            ) VALUES (?, ?, 'standalone-action', 'no_change', 'experience', '1', ?)
            """,
            (
                (USER_ID, "experience-job-1", TIMESTAMP),
                (USER_ID, "experience-job-2", TIMESTAMP),
            ),
        )
        experience_run_count = connection.execute(
            """
            SELECT COUNT(*)
            FROM agent_experience_extraction_runs
            WHERE action_id = 'standalone-action'
            """
        ).fetchone()[0]
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO agent_action_steps(
                    step_id, action_id, user_id, step_number, step_type,
                    step_name, status, user_request_text, user_message_id,
                    user_message_json, created_at
                ) VALUES ('duplicate-user-message', 'standalone-action', ?, 2,
                          'user_request', 'user request', 'success', 'hello',
                          'message-standalone', '{"text":"hello"}', ?)
                """,
                (USER_ID, TIMESTAMP),
            )
        connection.execute(
            """
            INSERT INTO agent_suggestions(
                suggestion_id, user_id, status, created_at, updated_at
            ) VALUES ('suggestion-restricted', ?, 'processing', ?, ?)
            """,
            (USER_ID, TIMESTAMP, TIMESTAMP),
        )
        connection.execute(
            """
            INSERT INTO agent_actions(
                action_id, user_id, suggestion_id, initial_user_message_id,
                status, execution_target_json, final_output,
                prompt_name, prompt_version, created_at, updated_at
            ) VALUES ('suggestion-action', ?, 'suggestion-restricted',
                      'message-suggestion', 'queued', '{"kind":"scratch"}',
                      '', 'action', '1.0', ?, ?)
            """,
            (USER_ID, TIMESTAMP, TIMESTAMP),
        )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "DELETE FROM agent_suggestions WHERE suggestion_id='suggestion-restricted'"
            )
        connection.execute(
            """
            INSERT INTO agent_process_events(
                event_id, suggestion_id, user_id, action_id, sequence,
                event_name, payload, created_at
            ) VALUES ('standalone-event', NULL, ?, 'standalone-action', 1,
                      'action_requested', '{}', ?)
            """,
            (USER_ID, TIMESTAMP),
        )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO agent_process_events(
                    event_id, suggestion_id, user_id, action_id, sequence,
                    event_name, payload, created_at
                ) VALUES ('standalone-event-duplicate', NULL, ?,
                          'standalone-action', 1, 'action_requested', '{}', ?)
                """,
                (USER_ID, TIMESTAMP),
            )

    assert action_columns["suggestion_id"] == 0
    assert "action_execution_id" not in suggestion_columns
    assert action_columns["initial_user_message_id"] == 1
    assert action_columns["execution_target_json"] == 1
    assert event_columns["suggestion_id"] == 0
    assert "'queued'" in action_sql
    assert "ON DELETE RESTRICT" in action_sql
    assert "uq_agent_action_steps_user_message" in indexes
    assert user_message_index_columns == ["user_id", "user_message_id"]
    assert "uq_agent_process_events_standalone_sequence" in indexes
    assert experience_run_count == 2


def test_v82_preserves_terminal_history_and_runtime_audit(tmp_path: Path) -> None:
    db_path = tmp_path / "runtime.db"
    _apply_before_v82(db_path)
    with sqlite3.connect(db_path) as connection:
        configure_connection(connection, BUSY_TIMEOUT_MS)
        with connection:
            _insert_user(connection)
            _insert_terminal_action(connection)
            _insert_terminal_history(connection)
            _insert_terminal_job_audit(connection)
            _insert_terminal_tool_audit(connection)
        action_before = connection.execute(
            "SELECT * FROM agent_actions WHERE action_id='action-1'"
        ).fetchone()
        steps_before = connection.execute(
            "SELECT * FROM agent_action_steps ORDER BY step_id"
        ).fetchall()
        event_before = connection.execute(
            "SELECT * FROM agent_process_events WHERE event_id='public-event-1'"
        ).fetchone()
        audit_before = connection.execute(
            """
            SELECT jobs.status, job_payloads.payload_json, attempts.status,
                   events.payload_json
            FROM jobs
            JOIN job_payloads ON job_payloads.job_id=jobs.job_id
            JOIN job_attempts AS attempts ON attempts.job_id=jobs.job_id
            JOIN process_events AS events ON events.process_id=jobs.process_id
            WHERE jobs.job_id='job-1'
            """
        ).fetchone()
        trigger_names_before = connection.execute(
            """
            SELECT name FROM sqlite_master
            WHERE type='trigger' AND tbl_name='agent_actions' ORDER BY name
            """
        ).fetchall()
        tool_audit_before = _load_terminal_tool_audit(connection)

    _apply_v82(db_path)

    with sqlite3.connect(db_path) as connection:
        configure_connection(connection, BUSY_TIMEOUT_MS)
        action_after = connection.execute(
            "SELECT * FROM agent_actions WHERE action_id='action-1'"
        ).fetchone()
        steps_after = connection.execute(
            "SELECT * FROM agent_action_steps ORDER BY step_id"
        ).fetchall()
        event_after = connection.execute(
            "SELECT * FROM agent_process_events WHERE event_id='public-event-1'"
        ).fetchone()
        audit_after = connection.execute(
            """
            SELECT jobs.status, job_payloads.payload_json, attempts.status,
                   events.payload_json
            FROM jobs
            JOIN job_payloads ON job_payloads.job_id=jobs.job_id
            JOIN job_attempts AS attempts ON attempts.job_id=jobs.job_id
            JOIN process_events AS events ON events.process_id=jobs.process_id
            WHERE jobs.job_id='job-1'
            """
        ).fetchone()
        trigger_names_after = connection.execute(
            """
            SELECT name FROM sqlite_master
            WHERE type='trigger' AND tbl_name='agent_actions' ORDER BY name
            """
        ).fetchall()
        tool_audit_after = _load_terminal_tool_audit(connection)
        fk_violations = connection.execute("PRAGMA foreign_key_check").fetchall()
        integrity = connection.execute("PRAGMA integrity_check").fetchone()

    assert action_before is not None and action_after is not None
    assert action_after[:3] == action_before[:3]
    assert action_after[3:6] == ("message-1", "success", '{"kind":"scratch"}')
    assert action_after[6:] == action_before[4:]
    assert [row[:22] + row[24:] for row in steps_after] == steps_before
    assert all(row[22:24] == (None, None) for row in steps_after)
    assert event_after == event_before
    assert audit_after == audit_before
    assert trigger_names_after == trigger_names_before
    assert tool_audit_after == tool_audit_before
    assert fk_violations == []
    assert integrity == ("ok",)


def test_v82_discards_legacy_reverse_action_pointer(tmp_path: Path) -> None:
    db_path = tmp_path / "runtime.db"
    _apply_before_v82(db_path)
    with sqlite3.connect(db_path) as connection:
        configure_connection(connection, BUSY_TIMEOUT_MS)
        with connection:
            _insert_user(connection)
            _insert_terminal_action(connection)
            connection.execute(
                """
                UPDATE agent_suggestions
                SET action_execution_id = 'stale-action-id'
                WHERE suggestion_id = 'suggestion-1'
                """
            )
        suggestion_rowid = connection.execute(
            """
            SELECT rowid FROM agent_suggestions
            WHERE suggestion_id = 'suggestion-1'
            """
        ).fetchone()[0]

    apply_migrations(db_path, BUSY_TIMEOUT_MS, load_default_migrations())

    with sqlite3.connect(db_path) as connection:
        suggestion_columns = {
            str(row[1])
            for row in connection.execute("PRAGMA table_info(agent_suggestions)")
        }
        canonical_link = connection.execute(
            """
            SELECT actions.action_id, actions.suggestion_id
            FROM agent_actions AS actions
            WHERE actions.action_id = 'action-1'
            """
        ).fetchone()
        migrated_rowid = connection.execute(
            """
            SELECT rowid FROM agent_suggestions
            WHERE suggestion_id = 'suggestion-1'
            """
        ).fetchone()[0]
        search_result = connection.execute(
            """
            SELECT suggestions.suggestion_id
            FROM memory_search_agent_suggestions_fts AS search
            JOIN agent_suggestions AS suggestions ON suggestions.rowid = search.rowid
            WHERE memory_search_agent_suggestions_fts MATCH 'approved'
            """
        ).fetchall()

    assert "action_execution_id" not in suggestion_columns
    assert canonical_link == ("action-1", "suggestion-1")
    assert migrated_rowid == suggestion_rowid
    assert search_result == [("suggestion-1",)]


def test_v82_preserves_action_rowids_for_external_content_fts(tmp_path: Path) -> None:
    db_path = tmp_path / "runtime.db"
    _apply_before_v82(db_path)
    with sqlite3.connect(db_path) as connection:
        configure_connection(connection, BUSY_TIMEOUT_MS)
        with connection:
            _insert_user(connection)
            _insert_terminal_action(
                connection,
                action_id="action-z",
                suggestion_id="suggestion-z",
                command_id=" message-z ",
            )
            _insert_terminal_action(
                connection,
                action_id="action-a",
                suggestion_id="suggestion-a",
                command_id=None,
            )
            connection.execute(
                "UPDATE agent_actions SET final_output='zebra' WHERE action_id='action-z'"
            )
            connection.execute(
                "UPDATE agent_actions SET final_output='alpha' WHERE action_id='action-a'"
            )
        rowids_before = connection.execute(
            "SELECT action_id, rowid FROM agent_actions ORDER BY action_id"
        ).fetchall()

    apply_migrations(db_path, BUSY_TIMEOUT_MS, load_default_migrations())

    with sqlite3.connect(db_path) as connection:
        configure_connection(connection, BUSY_TIMEOUT_MS)
        rowids_after = connection.execute(
            "SELECT action_id, rowid FROM agent_actions ORDER BY action_id"
        ).fetchall()
        alpha_match = connection.execute(
            """
            SELECT actions.action_id
            FROM memory_search_agent_actions_fts
            JOIN agent_actions AS actions
              ON actions.rowid = memory_search_agent_actions_fts.rowid
            WHERE memory_search_agent_actions_fts MATCH 'alpha'
            """
        ).fetchall()
        message_ids = connection.execute(
            """
            SELECT action_id, initial_user_message_id
            FROM agent_actions
            ORDER BY action_id
            """
        ).fetchall()

    assert rowids_after == rowids_before
    assert alpha_match == [("action-a",)]
    assert message_ids == [
        ("action-a", "action:action-a"),
        ("action-z", " message-z "),
    ]


def _setup_accepted_suggestion(connection: sqlite3.Connection) -> tuple[str, str]:
    connection.execute(
        """
        INSERT INTO agent_suggestions(
            suggestion_id, user_id, status, user_reaction, accepted_at,
            action_status, action_request_payload, created_at, updated_at
        ) VALUES ('suggestion-pending', ?, 'success', 'accepted', ?, 'idle',
                  '{"version":1}', ?, ?)
        """,
        (USER_ID, TIMESTAMP, TIMESTAMP, TIMESTAMP),
    )
    return ("accepted_suggestion", "suggestion-pending")


def _setup_active_action(connection: sqlite3.Connection) -> tuple[str, str]:
    _insert_terminal_action(connection, action_status="processing")
    connection.execute(
        "UPDATE agent_suggestions SET action_status='success' WHERE suggestion_id='suggestion-1'"
    )
    return ("action", "action-1")


def _setup_action_job(
    connection: sqlite3.Connection,
    *,
    status: str,
) -> tuple[str, str]:
    connection.execute(
        """
        INSERT INTO jobs(job_id, user_id, job_type, status, scheduled_at)
        VALUES ('job-active', ?, 'execute_action', ?, ?)
        """,
        (USER_ID, status, TIMESTAMP),
    )
    return ("action_job", "job-active")


def _setup_queued_job(connection: sqlite3.Connection) -> tuple[str, str]:
    return _setup_action_job(connection, status="queued")


def _setup_running_job(connection: sqlite3.Connection) -> tuple[str, str]:
    return _setup_action_job(connection, status="running")


def _setup_paused_job(connection: sqlite3.Connection) -> tuple[str, str]:
    return _setup_action_job(connection, status="paused")


def _setup_retryable_error_job(connection: sqlite3.Connection) -> tuple[str, str]:
    return _setup_action_job(connection, status="retryable_error")


def _setup_blocked_job(connection: sqlite3.Connection) -> tuple[str, str]:
    return _setup_action_job(connection, status="blocked")


def _setup_active_process(connection: sqlite3.Connection) -> tuple[str, str]:
    connection.execute(
        """
        INSERT INTO processes(
            process_id, user_id, kind, status, started_at, updated_at,
            heartbeat_at, next_event_seq
        ) VALUES ('process-active', ?, 'action', 'enqueued', ?, ?, ?, 1)
        """,
        (USER_ID, TIMESTAMP, TIMESTAMP, TIMESTAMP),
    )
    return ("action_process", "process-active")


def _setup_running_attempt(connection: sqlite3.Connection) -> tuple[str, str]:
    connection.execute(
        """
        INSERT INTO jobs(job_id, user_id, job_type, status, scheduled_at)
        VALUES ('job-terminal', ?, 'execute_action', 'completed', ?)
        """,
        (USER_ID, TIMESTAMP),
    )
    connection.execute(
        """
        INSERT INTO job_attempts(
            attempt_id, job_id, attempt_number, started_at, status
        ) VALUES ('attempt-running', 'job-terminal', 1, ?, 'running')
        """,
        (TIMESTAMP,),
    )
    return ("action_attempt", "attempt-running")


def _setup_pending_approval(connection: sqlite3.Connection) -> tuple[str, str]:
    _insert_terminal_action(connection)
    connection.execute(
        """
        INSERT INTO approval_sessions(
            approval_session_id, user_id, action_id, tool_request_id, tool_id,
            intent_class, approval_source, status, approved_capabilities_json,
            command_summary_json, requested_at, created_at
        ) VALUES ('approval-pending', ?, 'action-1', 'request-1', 'tool-1',
                  'surgical_edit', 'prompt', 'pending', '[]', '{}', ?, ?)
        """,
        (USER_ID, TIMESTAMP, TIMESTAMP),
    )
    return ("approval", "approval-pending")


def _insert_execution_session(connection: sqlite3.Connection, *, status: str) -> None:
    connection.execute(
        """
        INSERT INTO execution_sessions(
            execution_session_id, user_id, action_id, exec_mode, cwd_path,
            network_policy, capability_snapshot_json, status, started_at,
            completed_at
        ) VALUES ('session-1', ?, 'action-1', 'brokered_file_ops', '.',
                  'cloud-proxy-only', '{}', ?, ?, ?)
        """,
        (
            USER_ID,
            status,
            TIMESTAMP,
            None if status == "running" else TIMESTAMP,
        ),
    )


def _setup_tool_invocation(connection: sqlite3.Connection) -> tuple[str, str]:
    _insert_terminal_action(connection)
    _insert_execution_session(connection, status="completed")
    connection.execute(
        """
        INSERT INTO tool_definitions(
            tool_id, tool_name, tool_description, category, risk_level,
            input_schema_json, is_enabled, version, created_at, updated_at
        ) VALUES ('tool-1', 'Tool', 'Tool', 'editor', 'medium', '{}', 1, '1', ?, ?)
        """,
        (TIMESTAMP, TIMESTAMP),
    )
    connection.execute(
        """
        INSERT INTO tool_invocations(
            invocation_id, user_id, action_id, tool_id, execution_session_id,
            intent_class, started_at, status
        ) VALUES ('invocation-running', ?, 'action-1', 'tool-1', 'session-1',
                  'surgical_edit', ?, 'running')
        """,
        (USER_ID, TIMESTAMP),
    )
    return ("tool_invocation", "invocation-running")


def _setup_queued_tool_invocation(
    connection: sqlite3.Connection,
) -> tuple[str, str]:
    category, identifier = _setup_tool_invocation(connection)
    connection.execute(
        "UPDATE tool_invocations SET status='queued' WHERE invocation_id=?",
        (identifier,),
    )
    return (category, identifier)


def _setup_execution_session(connection: sqlite3.Connection) -> tuple[str, str]:
    _insert_terminal_action(connection)
    _insert_execution_session(connection, status="running")
    return ("execution_session", "session-1")


def _setup_runtime_resource(connection: sqlite3.Connection) -> tuple[str, str]:
    _insert_terminal_action(connection)
    _insert_execution_session(connection, status="completed")
    connection.execute(
        """
        INSERT INTO tool_runtime_resources(
            resource_id, execution_session_id, action_id, resource_kind,
            status, created_at, updated_at
        ) VALUES ('resource-active', 'session-1', 'action-1', 'temp_dir',
                  'active', ?, ?)
        """,
        (TIMESTAMP, TIMESTAMP),
    )
    return ("runtime_resource", "resource-active")


def _setup_cleanup_failed_resource(
    connection: sqlite3.Connection,
) -> tuple[str, str]:
    category, identifier = _setup_runtime_resource(connection)
    connection.execute(
        """
        UPDATE tool_runtime_resources
        SET status='cleanup_failed', cleanup_error='cleanup failed'
        WHERE resource_id=?
        """,
        (identifier,),
    )
    return (category, identifier)


BlockerSetup = Callable[[sqlite3.Connection], tuple[str, str]]


def _insert_inflight_action_lineage(
    connection: sqlite3.Connection,
    *,
    action_status: str,
    job_status: str,
    process_status: str,
) -> None:
    action_request_payload = (
        '{"version":1,"command_id":"message-1","screen_captures":[]}'
        if action_status == "idle"
        else None
    )
    connection.execute(
        """
        INSERT INTO agent_suggestions(
            suggestion_id, user_id, status, answer, prompt_name, prompt_version,
            has_suggestion, interaction_contract, user_reaction, accepted_at,
            action_status, action_request_payload, action_process_id,
            action_execution_id, action_command_id, action_started_at,
            created_at, updated_at
        ) VALUES ('suggestion-inflight', ?, 'success', 'approved suggestion',
                  'suggestion', '1.0', 1, 'action_offer', 'accepted', ?, ?, ?,
                  'process-inflight', 'action-inflight', 'message-1', ?, ?, ?)
        """,
        (
            USER_ID,
            TIMESTAMP,
            action_status,
            action_request_payload,
            None if action_status == "idle" else TIMESTAMP,
            TIMESTAMP,
            TIMESTAMP,
        ),
    )
    if action_status == "processing":
        connection.execute(
            """
            INSERT INTO agent_actions(
                action_id, user_id, suggestion_id, status, final_output,
                prompt_name, prompt_version, created_at, updated_at
            ) VALUES ('action-inflight', ?, 'suggestion-inflight', 'processing',
                      '', 'action', '1.0', ?, ?)
            """,
            (USER_ID, TIMESTAMP, TIMESTAMP),
        )
        connection.execute(
            """
            INSERT INTO agent_action_steps(
                step_id, action_id, user_id, step_number, step_type,
                step_name, status, thinking, created_at
            ) VALUES ('step-inflight', 'action-inflight', ?, 1, 'llm_output',
                      'thinking', 'processing', 'legacy checkpoint', ?)
            """,
            (USER_ID, TIMESTAMP),
        )
    connection.execute(
        """
        INSERT INTO processes(
            process_id, user_id, kind, status, suggestion_id, action_id,
            started_at, updated_at, heartbeat_at, current_job_id,
            next_event_seq
        ) VALUES ('process-inflight', ?, 'action', ?, 'suggestion-inflight',
                  'action-inflight', ?, ?, ?, 'job-inflight', 2)
        """,
        (USER_ID, process_status, TIMESTAMP, TIMESTAMP, TIMESTAMP),
    )
    connection.execute(
        """
        INSERT INTO jobs(
            job_id, user_id, job_type, process_id, status, attempt,
            scheduled_at, started_at, logical_key
        ) VALUES ('job-inflight', ?, 'execute_action', 'process-inflight', ?, 1,
                  ?, ?, 'action-inflight')
        """,
        (USER_ID, job_status, TIMESTAMP, TIMESTAMP),
    )
    connection.execute(
        """
        INSERT INTO job_payloads(job_id, payload_json, created_at)
        VALUES ('job-inflight', ?, ?)
        """,
        (
            json.dumps(
                {
                    "job_id": "job-inflight",
                    "process_id": "process-inflight",
                    "dispatch_kind": "start",
                    "action_id": "action-inflight",
                    "suggestion_id": "suggestion-inflight",
                    "user_id": USER_ID,
                    "command_id": "message-1",
                    "accepted_at": TIMESTAMP,
                    "enqueued_at": TIMESTAMP,
                    "screen_captures": [],
                }
            ),
            TIMESTAMP,
        ),
    )
    connection.execute(
        """
        INSERT INTO job_attempts(
            attempt_id, job_id, attempt_number, started_at, status
        ) VALUES ('attempt-inflight', 'job-inflight', 1, ?, 'running')
        """,
        (TIMESTAMP,),
    )
    connection.execute(
        """
        INSERT INTO process_events(
            process_id, event_seq, event_id, event_name, payload_json, created_at
        ) VALUES ('process-inflight', 1, 'internal-started', 'process_started',
                  '{"action_id":"action-inflight"}', ?)
        """,
        (TIMESTAMP,),
    )
    connection.execute(
        """
        INSERT INTO agent_process_events(
            event_id, suggestion_id, user_id, action_id, sequence,
            event_name, payload, created_at
        ) VALUES ('public-requested', 'suggestion-inflight', ?, NULL, 1,
                  'action_requested', ?, ?)
        """,
        (
            USER_ID,
            json.dumps(
                {
                    "data": {
                        "kind": "action",
                        "process_id": "process-inflight",
                        "suggestion_id": "suggestion-inflight",
                        "action_id": "action-inflight",
                        "command_id": "message-1",
                        "accepted_at": TIMESTAMP,
                    },
                    "meta": {},
                }
            ),
            TIMESTAMP,
        ),
    )


@pytest.mark.parametrize(
    ("action_status", "job_status", "process_status"),
    (
        ("idle", "queued", "enqueued"),
        ("processing", "running", "running"),
        ("processing", "paused", "paused"),
        ("processing", "blocked", "running"),
        ("processing", "retryable_error", "running"),
    ),
)
def test_v82_converges_valid_inflight_action_lineage(
    tmp_path: Path,
    action_status: str,
    job_status: str,
    process_status: str,
) -> None:
    db_path = tmp_path / "runtime.db"
    _apply_before_v82(db_path)
    with sqlite3.connect(db_path) as connection:
        configure_connection(connection, BUSY_TIMEOUT_MS)
        with connection:
            _insert_user(connection)
            _insert_inflight_action_lineage(
                connection,
                action_status=action_status,
                job_status=job_status,
                process_status=process_status,
            )

    apply_migrations(db_path, BUSY_TIMEOUT_MS, load_default_migrations())

    with sqlite3.connect(db_path) as connection:
        suggestion = connection.execute(
            """
            SELECT action_status, action_failure_code, action_failure_stage,
                   action_request_payload
            FROM agent_suggestions
            WHERE suggestion_id = 'suggestion-inflight'
            """
        ).fetchone()
        action = connection.execute(
            "SELECT status, error FROM agent_actions WHERE action_id='action-inflight'"
        ).fetchone()
        runtime = connection.execute(
            """
            SELECT jobs.status, processes.status, attempts.status
            FROM jobs
            JOIN processes ON processes.process_id = jobs.process_id
            JOIN job_attempts AS attempts ON attempts.job_id = jobs.job_id
            WHERE jobs.job_id = 'job-inflight'
            """
        ).fetchone()
        public_event = connection.execute(
            """
            SELECT action_id, sequence, payload
            FROM agent_process_events
            WHERE event_id = 'v82-cutover-public:suggestion-inflight'
            """
        ).fetchone()
        internal_event = connection.execute(
            """
            SELECT event_name, payload_json
            FROM process_events
            WHERE event_id = 'v82-cutover-internal:process-inflight'
            """
        ).fetchone()
        processing_steps = connection.execute(
            "SELECT COUNT(*) FROM agent_action_steps WHERE status='processing'"
        ).fetchone()[0]
        history = connection.execute(
            """
            SELECT action_status, action_failure_code, action_failure_stage,
                   action_request_payload_present, last_sequence
            FROM agent_suggestion_history
            WHERE suggestion_id = 'suggestion-inflight'
            """
        ).fetchone()

    assert suggestion == (
        "error",
        "ACTION_CREATION_CUTOVER",
        "resume_failed",
        None,
    )
    assert action is not None
    assert action[0] == "error"
    assert json.loads(str(action[1]))["error_code"] == "ACTION_CREATION_CUTOVER"
    assert runtime == ("failed", "failed", "failed")
    assert public_event is not None
    assert public_event[:2] == ("action-inflight", 2)
    assert json.loads(str(public_event[2]))["data"]["status"] == "error"
    assert internal_event is not None
    assert internal_event[0] == "stream_end"
    assert json.loads(str(internal_event[1]))["failure_code"] == (
        "ACTION_CREATION_CUTOVER"
    )
    assert processing_steps == 0
    assert history == (
        "error",
        "ACTION_CREATION_CUTOVER",
        "resume_failed",
        0,
        2,
    )

    with sqlite3.connect(db_path) as connection:
        configure_connection(connection, BUSY_TIMEOUT_MS)
        domain_before = tuple(
            line for line in connection.iterdump() if "migration_journal" not in line
        )
    apply_migrations(db_path, BUSY_TIMEOUT_MS, load_default_migrations())
    with sqlite3.connect(db_path) as connection:
        configure_connection(connection, BUSY_TIMEOUT_MS)
        domain_after = tuple(
            line for line in connection.iterdump() if "migration_journal" not in line
        )
    assert domain_after == domain_before


def test_v82_converges_inflight_approval_and_tool_runtime(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "runtime.db"
    _apply_before_v82(db_path)
    with sqlite3.connect(db_path) as connection:
        configure_connection(connection, BUSY_TIMEOUT_MS)
        with connection:
            _insert_user(connection)
            _insert_inflight_action_lineage(
                connection,
                action_status="processing",
                job_status="paused",
                process_status="paused",
            )
            connection.execute(
                """
                INSERT INTO execution_sessions(
                    execution_session_id, user_id, action_id, exec_mode,
                    cwd_path, network_policy, capability_snapshot_json,
                    status, started_at
                ) VALUES ('session-inflight', ?, 'action-inflight',
                          'brokered_file_ops', '.', 'cloud-proxy-only', '{}',
                          'running', ?)
                """,
                (USER_ID, TIMESTAMP),
            )
            connection.execute(
                """
                INSERT INTO tool_definitions(
                    tool_id, tool_name, tool_description, category, risk_level,
                    input_schema_json, is_enabled, version, created_at, updated_at
                ) VALUES ('tool-inflight', 'Tool', 'Tool', 'editor', 'medium',
                          '{}', 1, '1', ?, ?)
                """,
                (TIMESTAMP, TIMESTAMP),
            )
            connection.execute(
                """
                INSERT INTO tool_invocations(
                    invocation_id, user_id, action_id, tool_id,
                    execution_session_id, intent_class, started_at, status
                ) VALUES ('invocation-inflight', ?, 'action-inflight',
                          'tool-inflight', 'session-inflight', 'surgical_edit',
                          ?, 'running')
                """,
                (USER_ID, TIMESTAMP),
            )
            connection.execute(
                """
                INSERT INTO approval_sessions(
                    approval_session_id, user_id, action_id, tool_request_id,
                    tool_id, intent_class, approval_source, status,
                    approved_capabilities_json, command_summary_json,
                    requested_at, created_at
                ) VALUES ('approval-inflight', ?, 'action-inflight', 'request-1',
                          'tool-inflight', 'surgical_edit', 'prompt', 'pending',
                          '[]', '{}', ?, ?)
                """,
                (USER_ID, TIMESTAMP, TIMESTAMP),
            )
            connection.execute(
                """
                INSERT INTO tool_runtime_resources(
                    resource_id, execution_session_id, tool_invocation_id,
                    action_id, resource_kind, status, created_at, updated_at
                ) VALUES ('resource-inflight', 'session-inflight',
                          'invocation-inflight', 'action-inflight', 'temp_dir',
                          'active', ?, ?)
                """,
                (TIMESTAMP, TIMESTAMP),
            )

    apply_migrations(db_path, BUSY_TIMEOUT_MS, load_default_migrations())

    with sqlite3.connect(db_path) as connection:
        approval = connection.execute(
            "SELECT status, decided_at FROM approval_sessions"
        ).fetchone()
        tool = connection.execute(
            "SELECT status, completed_at FROM tool_invocations"
        ).fetchone()
        session = connection.execute(
            "SELECT status, completed_at FROM execution_sessions"
        ).fetchone()
        resource = connection.execute(
            "SELECT status FROM tool_runtime_resources"
        ).fetchone()
    assert approval is not None and approval[0] == "interrupted"
    assert approval[1] is not None
    assert tool is not None and tool[0] == "canceled"
    assert tool[1] is not None
    assert session is not None and session[0] == "canceled"
    assert session[1] is not None
    assert resource == ("active",)


@pytest.mark.parametrize("corruption", ("owner_mismatch", "duplicate_job"))
def test_v82_rejects_ambiguous_inflight_lineage_before_mutation(
    tmp_path: Path,
    corruption: str,
) -> None:
    db_path = tmp_path / "runtime.db"
    _apply_before_v82(db_path)
    with sqlite3.connect(db_path) as connection:
        configure_connection(connection, BUSY_TIMEOUT_MS)
        with connection:
            _insert_user(connection)
            _insert_inflight_action_lineage(
                connection,
                action_status="processing",
                job_status="running",
                process_status="running",
            )
            if corruption == "owner_mismatch":
                connection.execute(
                    """
                    UPDATE agent_suggestions
                    SET action_execution_id = 'different-action'
                    WHERE suggestion_id = 'suggestion-inflight'
                    """
                )
            else:
                connection.execute(
                    """
                    INSERT INTO jobs(
                        job_id, user_id, job_type, process_id, status,
                        scheduled_at, logical_key
                    ) VALUES ('job-duplicate', ?, 'execute_action',
                              'process-inflight', 'queued', ?, 'action-inflight')
                    """,
                    (USER_ID, TIMESTAMP),
                )
                duplicate_payload = connection.execute(
                    "SELECT payload_json FROM job_payloads WHERE job_id='job-inflight'"
                ).fetchone()[0]
                payload = json.loads(str(duplicate_payload))
                payload["job_id"] = "job-duplicate"
                connection.execute(
                    """
                    INSERT INTO job_payloads(job_id, payload_json, created_at)
                    VALUES ('job-duplicate', ?, ?)
                    """,
                    (json.dumps(payload), TIMESTAMP),
                )
        domain_before = tuple(
            line for line in connection.iterdump() if "migration_journal" not in line
        )

    with pytest.raises(MigrationError, match="v82 preflight blocked"):
        apply_migrations(db_path, BUSY_TIMEOUT_MS, load_default_migrations())

    with sqlite3.connect(db_path) as connection:
        configure_connection(connection, BUSY_TIMEOUT_MS)
        domain_after = tuple(
            line for line in connection.iterdump() if "migration_journal" not in line
        )
        schema_version = connection.execute(
            "SELECT current_version FROM schema_versions WHERE component='local_runtime'"
        ).fetchone()
    assert domain_after == domain_before
    assert schema_version == (81,)


@pytest.mark.parametrize("resource_status", ("active", "cleanup_failed"))
def test_v82_preserves_owned_runtime_resources_for_startup_cleanup(
    tmp_path: Path,
    resource_status: str,
) -> None:
    db_path = tmp_path / "runtime.db"
    _apply_before_v82(db_path)
    with sqlite3.connect(db_path) as connection:
        configure_connection(connection, BUSY_TIMEOUT_MS)
        with connection:
            _insert_user(connection)
            _, resource_id = _setup_runtime_resource(connection)
            if resource_status == "cleanup_failed":
                connection.execute(
                    """
                    UPDATE tool_runtime_resources
                    SET status='cleanup_failed', cleanup_error='cleanup failed'
                    WHERE resource_id=?
                    """,
                    (resource_id,),
                )

    apply_migrations(db_path, BUSY_TIMEOUT_MS, load_default_migrations())

    with sqlite3.connect(db_path) as connection:
        resource = connection.execute(
            "SELECT status FROM tool_runtime_resources WHERE resource_id=?",
            (resource_id,),
        ).fetchone()
        schema_version = connection.execute(
            "SELECT current_version FROM schema_versions WHERE component='local_runtime'"
        ).fetchone()
    assert resource == (resource_status,)
    assert schema_version == (load_default_migrations()[-1].version,)


@pytest.mark.parametrize(
    "setup_blocker",
    (
        _setup_accepted_suggestion,
        _setup_active_action,
        _setup_queued_job,
        _setup_running_job,
        _setup_paused_job,
        _setup_retryable_error_job,
        _setup_blocked_job,
        _setup_active_process,
        _setup_running_attempt,
        _setup_pending_approval,
        _setup_tool_invocation,
        _setup_queued_tool_invocation,
        _setup_execution_session,
    ),
    ids=lambda setup: setup.__name__.removeprefix("_setup_"),
)
def test_v82_rejects_inflight_state_before_domain_mutation(
    tmp_path: Path,
    setup_blocker: BlockerSetup,
) -> None:
    db_path = tmp_path / "runtime.db"
    _apply_before_v82(db_path)
    with sqlite3.connect(db_path) as connection:
        configure_connection(connection, BUSY_TIMEOUT_MS)
        with connection:
            _insert_user(connection)
            category, identifier = setup_blocker(connection)
        domain_before = tuple(
            line for line in connection.iterdump() if "migration_journal" not in line
        )

    with pytest.raises(
        MigrationError,
        match=rf"category={category} id={identifier} status=",
    ):
        apply_migrations(db_path, BUSY_TIMEOUT_MS, load_default_migrations())

    with sqlite3.connect(db_path) as connection:
        configure_connection(connection, BUSY_TIMEOUT_MS)
        domain_after = tuple(
            line for line in connection.iterdump() if "migration_journal" not in line
        )
        schema_version = connection.execute(
            """
            SELECT current_version FROM schema_versions
            WHERE component='local_runtime'
            """
        ).fetchone()
        journal = connection.execute(
            """
            SELECT status FROM migration_journal
            WHERE migration_name=? ORDER BY started_at DESC LIMIT 1
            """,
            (MIGRATION_NAME,),
        ).fetchone()

    assert domain_after == domain_before
    assert schema_version == (81,)
    assert journal == ("failed",)
