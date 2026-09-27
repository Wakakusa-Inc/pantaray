from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from pantaray_agents.local_runtime.storage.migrations import (
    MigrationError,
    load_default_migrations,
)
from pantaray_agents.local_runtime.storage.migrations.connection import (
    configure_connection,
)

from .support import (
    _insert_user,
    _migrations_through,
    apply_migrations,
)

BUSY_TIMEOUT_MS = 1_000
V89_MIGRATION_NAME = "0089_action_user_state_contract.sql"
TIMESTAMP = "2026-08-29T00:00:00Z"


def test_v89_enforces_three_user_states_and_indexes_visible_timeline(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "runtime.db"
    apply_migrations(
        db_path,
        BUSY_TIMEOUT_MS,
        _migrations_through(load_default_migrations(), V89_MIGRATION_NAME),
    )
    with sqlite3.connect(db_path) as connection:
        configure_connection(connection, BUSY_TIMEOUT_MS)
        with connection:
            _insert_user(connection, "user-1")
            connection.execute(
                """
                INSERT INTO agent_actions(
                    action_id,user_id,initial_user_message_id,execution_target_json,
                    status,final_output,prompt_name,prompt_version,created_at,updated_at
                ) VALUES ('action-1','user-1','message-1','{"kind":"scratch"}',
                          'processing','','action','1',?,?)
                """,
                (TIMESTAMP, TIMESTAMP),
            )
            connection.execute(
                """
                INSERT INTO processes(
                    process_id,user_id,kind,status,action_id,started_at,updated_at,
                    heartbeat_at,next_event_seq
                ) VALUES ('process-1','user-1','action','running','action-1',?,?,?,1)
                """,
                (TIMESTAMP, TIMESTAMP, TIMESTAMP),
            )
            connection.executemany(
                """
                INSERT INTO agent_action_steps(
                    step_id,action_id,user_id,step_number,local_step_number,
                    short_step_id,step_type,step_name,status,goal_handle,
                    user_request_text,user_message_id,user_message_json,
                    accepted_sequence,adoption_canceled_at,expected_process_id,
                    adopted_process_id,created_at
                ) VALUES (?,?,?, ?,?,?, 'user_request','user_request','success','S',
                          ?,?,'{}', ?,?,?,?,?)
                """,
                (
                    (
                        "adopted",
                        "action-1",
                        "user-1",
                        1,
                        1,
                        "S-1-USER",
                        "adopted request",
                        "message-adopted",
                        1,
                        None,
                        None,
                        "process-1",
                        TIMESTAMP,
                    ),
                    (
                        "pending",
                        "action-1",
                        "user-1",
                        None,
                        None,
                        None,
                        "pending request",
                        "message-pending",
                        2,
                        None,
                        "process-1",
                        None,
                        TIMESTAMP,
                    ),
                    (
                        "not-executed",
                        "action-1",
                        "user-1",
                        None,
                        None,
                        None,
                        "canceled request",
                        "message-canceled",
                        3,
                        TIMESTAMP,
                        "process-1",
                        None,
                        TIMESTAMP,
                    ),
                ),
            )

        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO agent_action_steps(
                    step_id,action_id,user_id,step_type,step_name,status,goal_handle,
                    user_request_text,user_message_id,user_message_json,
                    accepted_sequence,created_at
                ) VALUES ('unowned','action-1','user-1','user_request','user_request',
                          'success','S','invalid','message-invalid','{}',4,?)
                """,
                (TIMESTAMP,),
            )
        states = connection.execute(
            """
            SELECT step_id,step_number,adoption_canceled_at,expected_process_id,
                   adopted_process_id
            FROM agent_action_steps ORDER BY accepted_sequence
            """
        ).fetchall()
        plan = connection.execute(
            """
            EXPLAIN QUERY PLAN
            SELECT step_id FROM agent_action_steps
            WHERE action_id = ? AND step_number IS NOT NULL
              AND step_type IN ('user_request','tool_execution')
            ORDER BY step_number DESC, step_id DESC LIMIT 20
            """,
            ("action-1",),
        ).fetchall()
        violations = connection.execute("PRAGMA foreign_key_check").fetchall()

    assert states == [
        ("adopted", 1, None, None, "process-1"),
        ("pending", None, None, "process-1", None),
        ("not-executed", None, TIMESTAMP, "process-1", None),
    ]
    assert any("idx_agent_action_steps_action_timeline" in str(row[3]) for row in plan)
    assert violations == []


def test_v89_refuses_to_mark_a_nonfresh_runtime_current(tmp_path: Path) -> None:
    db_path = tmp_path / "runtime.db"
    migrations = _migrations_through(
        load_default_migrations(),
        V89_MIGRATION_NAME,
    )
    apply_migrations(db_path, BUSY_TIMEOUT_MS, migrations[:-1])
    with sqlite3.connect(db_path) as connection:
        _insert_user(connection, "legacy-user")

    with pytest.raises(MigrationError, match="v89 requires a fresh local runtime"):
        apply_migrations(db_path, BUSY_TIMEOUT_MS, migrations)

    with sqlite3.connect(db_path) as connection:
        version = connection.execute(
            "SELECT current_version FROM schema_versions "
            "WHERE component = 'local_runtime'"
        ).fetchone()
        user = connection.execute("SELECT user_id FROM users").fetchone()
        journal = connection.execute(
            "SELECT status FROM migration_journal WHERE migration_name = ? "
            "ORDER BY started_at DESC LIMIT 1",
            (V89_MIGRATION_NAME,),
        ).fetchone()
    assert version == (88,)
    assert user == ("legacy-user",)
    assert journal == ("failed",)
