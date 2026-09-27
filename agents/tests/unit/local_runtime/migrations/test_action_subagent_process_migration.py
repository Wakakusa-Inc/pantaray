from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from pantaray_agents.local_runtime.storage.migrations import (
    apply_migrations,
    load_default_migrations,
)
from pantaray_agents.local_runtime.storage.migrations.connection import (
    configure_connection,
)

from .support import _insert_user, _migrations_through

BUSY_TIMEOUT_MS = 1_000
V92_MIGRATION_NAME = "0092_action_history_recency_indexes.sql"
TIMESTAMP = "2026-09-01T00:00:00Z"
PRESERVED_PROCESS_OBJECTS = (
    "idx_processes_kind_status",
    "idx_processes_terminal_event_id",
    "idx_processes_user_updated",
    "trg_action_user_process_identity_insert",
    "trg_action_user_process_identity_update",
    "trg_action_user_referenced_process_kind",
    "uq_processes_active_action",
    "uq_processes_user_action_process",
)


def _insert_action(
    connection: sqlite3.Connection, action_id: str, user_id: str
) -> None:
    connection.execute(
        """
        INSERT INTO agent_actions(
            action_id,user_id,initial_user_message_id,execution_target_json,
            status,final_output,prompt_name,prompt_version,created_at,updated_at
        ) VALUES (?,?,?,'{"kind":"scratch"}',
                  'processing','','action','1',?,?)
        """,
        (action_id, user_id, f"message-{action_id}", TIMESTAMP, TIMESTAMP),
    )


def _insert_process(
    connection: sqlite3.Connection,
    process_id: str,
    *,
    user_id: str = "user-1",
    kind: str = "action_subagent",
    status: str = "running",
    action_id: str = "action-1",
    parent_process_id: str | None = "parent-1",
) -> None:
    connection.execute(
        """
        INSERT INTO processes(
            process_id,user_id,kind,status,action_id,started_at,updated_at,
            heartbeat_at,next_event_seq,parent_process_id
        ) VALUES (?,?,?,?,?,?,?,?,1,?)
        """,
        (
            process_id,
            user_id,
            kind,
            status,
            action_id,
            TIMESTAMP,
            TIMESTAMP,
            TIMESTAMP,
            parent_process_id,
        ),
    )


def _seed_parent_processes(connection: sqlite3.Connection) -> None:
    _insert_user(connection, "user-1")
    _insert_user(connection, "user-2")
    _insert_action(connection, "action-1", "user-1")
    _insert_action(connection, "action-2", "user-1")
    _insert_action(connection, "action-3", "user-2")
    for process_id, user_id, kind, status, action_id in (
        ("parent-1", "user-1", "action", "running", "action-1"),
        ("parent-terminal", "user-1", "action", "completed", "action-1"),
        ("parent-action-2", "user-1", "action", "running", "action-2"),
        ("parent-user-2", "user-2", "action", "running", "action-3"),
        ("parent-non-action", "user-1", "insight", "running", "action-1"),
    ):
        _insert_process(
            connection,
            process_id,
            user_id=user_id,
            kind=kind,
            status=status,
            action_id=action_id,
            parent_process_id=None,
        )


def test_v93_preserves_existing_process_dependencies_and_schema_objects(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "runtime.db"
    migrations = load_default_migrations()
    apply_migrations(
        db_path,
        BUSY_TIMEOUT_MS,
        _migrations_through(migrations, V92_MIGRATION_NAME),
    )
    with sqlite3.connect(db_path) as connection:
        configure_connection(connection, BUSY_TIMEOUT_MS)
        with connection:
            _insert_user(connection, "user-1")
            _insert_action(connection, "action-1", "user-1")
            connection.execute(
                """
                INSERT INTO processes(
                    process_id,user_id,kind,status,action_id,started_at,
                    updated_at,heartbeat_at,next_event_seq
                ) VALUES ('process-1','user-1','action','running','action-1',
                          ?,?,?,1)
                """,
                (TIMESTAMP, TIMESTAMP, TIMESTAMP),
            )
            connection.execute(
                """
                INSERT INTO jobs(
                    job_id,user_id,job_type,process_id,status,scheduled_at,logical_key
                ) VALUES ('job-1','user-1','execute_action','process-1',
                          'queued',?,'action-1')
                """,
                (TIMESTAMP,),
            )
            connection.execute(
                "INSERT INTO process_events(process_id,event_seq,event_id,event_name,"
                "payload_json,created_at) VALUES "
                "('process-1',1,'event-1','process_started','{}',?)",
                (TIMESTAMP,),
            )
            connection.execute(
                """
                INSERT INTO agent_action_steps(
                    step_id,action_id,user_id,step_number,local_step_number,
                    short_step_id,step_type,step_name,status,goal_handle,
                    user_request_text,user_message_id,user_message_json,
                    accepted_sequence,adopted_process_id,created_at
                ) VALUES (
                    'step-1','action-1','user-1',1,1,'S-1-USER',
                    'user_request','user_request','success','S','request',
                    'message-1','{}',1,'process-1',?
                )
                """,
                (TIMESTAMP,),
            )

    apply_migrations(db_path, BUSY_TIMEOUT_MS, load_default_migrations())

    with sqlite3.connect(db_path) as connection:
        configure_connection(connection, BUSY_TIMEOUT_MS)
        process = connection.execute(
            "SELECT process_id,user_id,kind,status,action_id,parent_process_id,"
            "result_collected_at FROM processes WHERE process_id='process-1'"
        ).fetchone()
        job = connection.execute(
            "SELECT job_id,process_id FROM jobs WHERE job_id='job-1'"
        ).fetchone()
        event = connection.execute(
            "SELECT event_id,process_id FROM process_events WHERE event_id='event-1'"
        ).fetchone()
        step = connection.execute(
            "SELECT step_id,adopted_process_id FROM agent_action_steps "
            "WHERE step_id='step-1'"
        ).fetchone()
        objects = tuple(
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE name IN (?,?,?,?,?,?,?,?) "
                "ORDER BY name",
                PRESERVED_PROCESS_OBJECTS,
            )
        )
        violations = connection.execute("PRAGMA foreign_key_check").fetchall()

    assert process == (
        "process-1",
        "user-1",
        "action",
        "running",
        "action-1",
        None,
        None,
    )
    assert job == ("job-1", "process-1")
    assert event == ("event-1", "process-1")
    assert step == ("step-1", "process-1")
    assert objects == PRESERVED_PROCESS_OBJECTS
    assert violations == []


def test_v93_enforces_child_lineage_capacity_and_collection(tmp_path: Path) -> None:
    db_path = tmp_path / "runtime.db"
    apply_migrations(db_path, BUSY_TIMEOUT_MS, load_default_migrations())
    with sqlite3.connect(db_path) as connection:
        configure_connection(connection, BUSY_TIMEOUT_MS)
        with connection:
            _seed_parent_processes(connection)
            _insert_process(connection, "child-1")

        invalid_parents = (
            ("orphan", "user-1", "action-1", "missing"),
            ("cross-user", "user-2", "action-3", "parent-1"),
            ("cross-action", "user-1", "action-2", "parent-1"),
            ("non-action", "user-1", "action-1", "parent-non-action"),
            ("terminal", "user-1", "action-1", "parent-terminal"),
            ("nested", "user-1", "action-1", "child-1"),
        )
        for process_id, user_id, action_id, parent_process_id in invalid_parents:
            with pytest.raises(sqlite3.IntegrityError):
                _insert_process(
                    connection,
                    process_id,
                    user_id=user_id,
                    action_id=action_id,
                    parent_process_id=parent_process_id,
                )

        for index in range(2, 5):
            _insert_process(connection, f"child-{index}")
        with pytest.raises(sqlite3.IntegrityError, match="active child limit exceeded"):
            _insert_process(connection, "child-5")

        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "UPDATE processes SET result_collected_at=? WHERE process_id='child-2'",
                (TIMESTAMP,),
            )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "UPDATE processes SET kind='insight' WHERE process_id='parent-1'"
            )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "UPDATE processes SET result_collected_at=? "
                "WHERE process_id='parent-1'",
                (TIMESTAMP,),
            )

        connection.execute(
            "UPDATE processes SET status='completed' WHERE process_id='child-1'"
        )
        connection.execute(
            "UPDATE processes SET result_collected_at=? WHERE process_id='child-1'",
            (TIMESTAMP,),
        )
        _insert_process(connection, "child-5")
        _insert_process(connection, "child-terminal", status="completed")
        with pytest.raises(sqlite3.IntegrityError, match="active child limit exceeded"):
            connection.execute(
                "UPDATE processes SET status='running' "
                "WHERE process_id='child-terminal'"
            )

        active_count = connection.execute(
            "SELECT COUNT(*) FROM processes WHERE parent_process_id='parent-1' "
            "AND status IN ('enqueued','running','paused')"
        ).fetchone()
        collected = connection.execute(
            "SELECT status,result_collected_at FROM processes "
            "WHERE process_id='child-1'"
        ).fetchone()
        connection.execute(
            "UPDATE processes SET status='completed' WHERE process_id='parent-1'"
        )
        connection.execute(
            "UPDATE processes SET status='canceled' WHERE process_id='child-2'"
        )
        connection.execute(
            "UPDATE processes SET status='enqueued' WHERE process_id='child-3'"
        )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("DELETE FROM processes WHERE process_id='parent-1'")
        connection.execute("DELETE FROM users WHERE user_id='user-1'")
        remaining_processes = connection.execute(
            "SELECT process_id FROM processes ORDER BY process_id"
        ).fetchall()

    assert active_count == (4,)
    assert collected == ("completed", TIMESTAMP)
    assert remaining_processes == [("parent-user-2",)]
