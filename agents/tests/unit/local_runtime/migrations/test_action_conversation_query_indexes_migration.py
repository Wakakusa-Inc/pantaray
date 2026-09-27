import sqlite3
from pathlib import Path

from pantaray_agents.local_runtime.storage.migrations import (
    apply_migrations,
    load_default_migrations,
)
from pantaray_agents.local_runtime.storage.migrations.connection import (
    configure_connection,
)

from .support import _insert_user, _migrations_through

BUSY_TIMEOUT_MS = 1_000
TIMESTAMP = "2026-08-30T00:00:00Z"
V90_MIGRATION_NAME = "0090_action_run_timeline_index.sql"
V91_MIGRATION_NAME = "0091_action_conversation_query_indexes.sql"


def _seed_action_history(connection: sqlite3.Connection) -> None:
    _insert_user(connection, "user-1")
    connection.execute(
        """INSERT INTO agent_actions(
        action_id,user_id,initial_user_message_id,execution_target_json,status,
        final_output,prompt_name,prompt_version,created_at,updated_at)
        VALUES ('action-1','user-1','message-1','{"kind":"scratch"}',
                'processing','','action','1',?,?)""",
        (TIMESTAMP, TIMESTAMP),
    )
    connection.execute(
        """INSERT INTO processes(
        process_id,user_id,kind,status,action_id,started_at,updated_at,
        heartbeat_at,next_event_seq)
        VALUES ('run-1','user-1','action','success','action-1',?,?,?,1)""",
        (TIMESTAMP, TIMESTAMP, TIMESTAMP),
    )
    connection.executemany(
        """INSERT INTO agent_action_steps(
        step_id,action_id,user_id,step_number,local_step_number,short_step_id,
        step_type,step_name,status,goal_handle,user_request_text,user_message_id,
        user_message_json,accepted_sequence,expected_process_id,
        adopted_process_id,created_at)
        VALUES (?,'action-1','user-1',?,?,?,'user_request','user_request',
                'success','S',?,?, '{}',?,?,?,?)""",
        (
            (
                "adopted",
                1,
                1,
                "S-1-USER",
                "adopted request",
                "message-adopted",
                1,
                None,
                "run-1",
                TIMESTAMP,
            ),
            (
                "unadopted",
                None,
                None,
                None,
                "pending request",
                "message-pending",
                2,
                "run-1",
                None,
                TIMESTAMP,
            ),
        ),
    )


def test_v91_preserves_history_and_adds_direct_query_indexes(tmp_path: Path) -> None:
    db_path = tmp_path / "runtime.db"
    migrations = load_default_migrations()
    through_v90 = _migrations_through(migrations, V90_MIGRATION_NAME)
    through_v91 = _migrations_through(migrations, V91_MIGRATION_NAME)
    apply_migrations(db_path, BUSY_TIMEOUT_MS, through_v90)
    with sqlite3.connect(db_path) as connection:
        configure_connection(connection, BUSY_TIMEOUT_MS)
        with connection:
            _seed_action_history(connection)

    apply_migrations(db_path, BUSY_TIMEOUT_MS, through_v91)
    with sqlite3.connect(db_path) as connection:
        configure_connection(connection, BUSY_TIMEOUT_MS)
        retained = connection.execute(
            "SELECT step_id FROM agent_action_steps ORDER BY accepted_sequence"
        ).fetchall()
        adopted_plan = connection.execute(
            """EXPLAIN QUERY PLAN SELECT adopted_process_id
            FROM agent_action_steps
              INDEXED BY idx_agent_action_steps_adopted_user_timeline
            WHERE user_id='user-1' AND action_id='action-1'
              AND step_number IS NOT NULL AND step_type='user_request'
              AND status='success' AND adopted_process_id IS NOT NULL
              AND step_number<=100
            ORDER BY step_number DESC,step_id DESC LIMIT 1"""
        ).fetchall()
        unadopted_plan = connection.execute(
            """EXPLAIN QUERY PLAN SELECT step_id FROM agent_action_steps
              INDEXED BY idx_agent_action_steps_unadopted_user_sequence
            WHERE user_id='user-1' AND action_id='action-1'
              AND step_type='user_request' AND step_number IS NULL
              AND adopted_process_id IS NULL AND accepted_sequence IS NOT NULL
            ORDER BY accepted_sequence DESC,step_id DESC LIMIT 2"""
        ).fetchall()

    details = tuple(str(row[3]) for row in (*adopted_plan, *unadopted_plan))
    assert retained == [("adopted",), ("unadopted",)]
    assert any(
        "USING INDEX idx_agent_action_steps_adopted_user_timeline" in row
        for row in details
    )
    assert any(
        "USING INDEX idx_agent_action_steps_unadopted_user_sequence" in row
        for row in details
    )
    assert all("TEMP B-TREE" not in row for row in details)
