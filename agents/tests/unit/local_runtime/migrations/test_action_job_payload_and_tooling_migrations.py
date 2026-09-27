from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from pantaray_agents.local_runtime.storage.migrations import (
    MigrationError,
)

from .support import (
    _insert_user,
    apply_migrations,
    load_default_migrations,
)


def test_action_job_payload_enqueued_at_migration_backfills_existing_jobs(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "runtime.db"
    apply_migrations(
        db_path=db_path,
        busy_timeout_ms=1_000,
        migrations=load_default_migrations()[:20],
    )

    with sqlite3.connect(db_path) as connection:
        _insert_user(connection, "user-1")
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
                heartbeat_at,
                next_event_seq
            ) VALUES (
                'process-1',
                'user-1',
                'action',
                'enqueued',
                'suggestion-1',
                'action-1',
                '2026-03-27T00:00:00Z',
                '2026-03-27T00:00:00Z',
                '2026-03-27T00:00:00Z',
                1
            )
            """
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
                logical_key
            ) VALUES (
                'job-1',
                'user-1',
                'execute_action',
                'process-1',
                'queued',
                '2026-03-27T00:00:00Z',
                'action-1'
            )
            """
        )
        connection.execute(
            """
            INSERT INTO job_payloads(job_id, payload_json)
            VALUES (
                'job-1',
                '{"job_id":"job-1","process_id":"process-1","dispatch_kind":"start","action_id":"action-1","suggestion_id":"suggestion-1","user_id":"user-1","command_id":"command-1","accepted_at":"2026-03-27T00:00:00Z","screen_captures":[]}'
            )
            """
        )

    apply_migrations(
        db_path=db_path,
        busy_timeout_ms=1_000,
        migrations=load_default_migrations()[:21],
    )

    with sqlite3.connect(db_path) as connection:
        payload_row = connection.execute(
            """
            SELECT json_extract(payload_json, '$.enqueued_at')
            FROM job_payloads
            WHERE job_id = 'job-1'
            """
        ).fetchone()

    assert payload_row == ("2026-03-27T00:00:00Z",)


def test_action_job_payload_enqueued_at_migration_fails_for_invalid_execute_action_payload(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "runtime.db"
    apply_migrations(
        db_path=db_path,
        busy_timeout_ms=1_000,
        migrations=load_default_migrations()[:20],
    )

    with sqlite3.connect(db_path) as connection:
        _insert_user(connection, "user-1")
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
                heartbeat_at,
                next_event_seq
            ) VALUES (
                'process-1',
                'user-1',
                'action',
                'enqueued',
                'suggestion-1',
                'action-1',
                '2026-03-27T00:00:00Z',
                '2026-03-27T00:00:00Z',
                '2026-03-27T00:00:00Z',
                1
            )
            """
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
                logical_key
            ) VALUES (
                'job-1',
                'user-1',
                'execute_action',
                'process-1',
                'queued',
                '2026-03-27T00:00:00Z',
                'action-1'
            )
            """
        )
        connection.execute(
            """
            INSERT INTO job_payloads(job_id, payload_json)
            VALUES (
                'job-1',
                '{"job_id":"job-1","process_id":"process-1","dispatch_kind":"start","action_id":"action-1","suggestion_id":"suggestion-1","user_id":"user-1","command_id":"command-1","screen_captures":[]}'
            )
            """
        )

    with pytest.raises(MigrationError, match="missing enqueued_at after migration"):
        apply_migrations(
            db_path=db_path,
            busy_timeout_ms=1_000,
            migrations=load_default_migrations(),
        )


def test_apply_migrations_adds_tooling_contract_columns(tmp_path: Path) -> None:
    db_path = tmp_path / "runtime.db"

    apply_migrations(
        db_path=db_path,
        busy_timeout_ms=1_000,
        migrations=load_default_migrations()[:9],
    )

    with sqlite3.connect(db_path) as connection:
        workspace_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(workspaces)")
        }
        execution_session_columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(execution_sessions)")
        }
        tool_definition_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(tool_definitions)")
        }
        tool_invocation_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(tool_invocations)")
        }
        approval_session_columns = connection.execute(
            "PRAGMA table_info(approval_sessions)"
        ).fetchall()
        approval_session_foreign_keys = connection.execute(
            "PRAGMA foreign_key_list(approval_sessions)"
        ).fetchall()

    assert "kind" in workspace_columns
    assert "root_id" in workspace_columns
    assert "normalized_path" in workspace_columns
    assert "exec_mode" in execution_session_columns
    assert "capability_snapshot_json" in execution_session_columns
    assert "intent_class" in tool_definition_columns
    assert "required_capabilities_json" in tool_definition_columns
    assert "invocation_id" in tool_invocation_columns
    assert "intent_class" in tool_invocation_columns
    tool_invocation_column = next(
        row for row in approval_session_columns if str(row[1]) == "tool_invocation_id"
    )
    assert int(tool_invocation_column[3]) == 0
    claimed_at_column = next(
        row for row in approval_session_columns if str(row[1]) == "claimed_at"
    )
    assert int(claimed_at_column[3]) == 0
    tool_invocation_fk = next(
        row
        for row in approval_session_foreign_keys
        if str(row[3]) == "tool_invocation_id"
    )
    assert str(tool_invocation_fk[6]).upper() == "SET NULL"
    action_fk = next(
        row for row in approval_session_foreign_keys if str(row[3]) == "action_id"
    )
    assert str(action_fk[6]).upper() == "CASCADE"


def test_apply_migrations_uses_documented_activity_capture_schema(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "runtime.db"

    apply_migrations(
        db_path=db_path,
        busy_timeout_ms=1_000,
        migrations=load_default_migrations(),
    )

    with sqlite3.connect(db_path) as connection:
        activity_log_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(activity_logs)")
        }
        activity_summary_columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(activity_summaries)")
        }
        table_names = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }

    assert "screen_captures" not in table_names
    assert {
        "log_id",
        "user_id",
        "period_start",
        "period_end",
        "description",
        "status",
        "error",
        "prompt_text",
        "prompt_name",
        "prompt_version",
        "source_capture_paths",
        "used_image_count",
        "created_at",
        "updated_at",
    } <= activity_log_columns
    assert {
        "summary_id",
        "user_id",
        "summary_type",
        "period_start",
        "period_end",
        "summary",
        "status",
        "error",
        "prompt_text",
        "prompt_name",
        "prompt_version",
        "source_ids",
        "created_at",
        "updated_at",
    } <= activity_summary_columns
    assert "content_json" not in activity_log_columns
    assert "summary_text" not in activity_summary_columns
