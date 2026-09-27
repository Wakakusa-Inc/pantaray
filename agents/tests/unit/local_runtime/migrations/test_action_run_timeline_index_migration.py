from __future__ import annotations

import sqlite3
from collections.abc import Sequence
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
TARGET_PROCESS_ID = "process-target"
V90_MIGRATION_NAME = "0090_action_run_timeline_index.sql"
RUN_START_QUERY = """
SELECT step_id
FROM agent_action_steps
WHERE user_id = ? AND action_id = ? AND adopted_process_id = ?
ORDER BY step_number ASC, step_id ASC
LIMIT 1
"""
RUN_PARAMETERS = ("user-1", "action-1", TARGET_PROCESS_ID)


def _insert_action(connection: sqlite3.Connection) -> None:
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


def _insert_runs(
    connection: sqlite3.Connection,
    runs: Sequence[tuple[str, int]],
) -> None:
    connection.executemany(
        """
        INSERT INTO processes(
            process_id,user_id,kind,status,action_id,started_at,updated_at,
            heartbeat_at,next_event_seq
        ) VALUES (?,'user-1','action','success','action-1',?,?,?,1)
        """,
        ((process_id, TIMESTAMP, TIMESTAMP, TIMESTAMP) for process_id, _ in runs),
    )
    connection.executemany(
        """
        INSERT INTO agent_action_steps(
            step_id,action_id,user_id,step_number,local_step_number,
            short_step_id,step_type,step_name,status,goal_handle,
            user_request_text,user_message_id,user_message_json,
            accepted_sequence,adopted_process_id,created_at
        ) VALUES (?,'action-1','user-1',?,?,?,'user_request','user_request',
                  'success','S',?,?,'{}',?,?,?)
        """,
        (
            (
                f"step-{sequence:04d}",
                sequence,
                sequence,
                f"S-{sequence}-USER",
                f"request {sequence}",
                f"message-{sequence}",
                sequence,
                process_id,
                TIMESTAMP,
            )
            for process_id, sequence in runs
        ),
    )


def _execute_with_vm_step_count(
    connection: sqlite3.Connection,
) -> tuple[tuple[str] | None, int]:
    vm_steps = 0

    def count_vm_step() -> int:
        nonlocal vm_steps
        vm_steps += 1
        return 0

    connection.set_progress_handler(count_vm_step, 1)
    try:
        row = connection.execute(RUN_START_QUERY, RUN_PARAMETERS).fetchone()
    finally:
        connection.set_progress_handler(None, 0)
    return row, vm_steps


def test_v90_preserves_runs_and_bounds_run_start_lookup(tmp_path: Path) -> None:
    db_path = tmp_path / "runtime.db"
    migrations = _migrations_through(load_default_migrations(), V90_MIGRATION_NAME)
    apply_migrations(db_path, BUSY_TIMEOUT_MS, migrations[:-1])
    with sqlite3.connect(db_path) as connection:
        configure_connection(connection, BUSY_TIMEOUT_MS)
        with connection:
            _insert_user(connection, "user-1")
            _insert_action(connection)
            _insert_runs(connection, ((TARGET_PROCESS_ID, 200),))

    apply_migrations(db_path, BUSY_TIMEOUT_MS, migrations)
    with sqlite3.connect(db_path) as connection:
        configure_connection(connection, BUSY_TIMEOUT_MS)
        retained_row = connection.execute(
            "SELECT step_id,adopted_process_id FROM agent_action_steps"
        ).fetchone()
        prefix_plan = connection.execute(
            """
            EXPLAIN QUERY PLAN SELECT step_id FROM agent_action_steps
            WHERE user_id=? AND action_id=? AND adopted_process_id=?
            """,
            RUN_PARAMETERS,
        ).fetchall()
        ordered_plan = connection.execute(
            f"EXPLAIN QUERY PLAN {RUN_START_QUERY}", RUN_PARAMETERS
        ).fetchall()
        _execute_with_vm_step_count(connection)
        first_row, baseline_vm_steps = _execute_with_vm_step_count(connection)

        with connection:
            _insert_runs(
                connection,
                tuple(
                    (f"process-old-{sequence}", sequence) for sequence in range(1, 129)
                ),
            )
        row_after_growth, grown_vm_steps = _execute_with_vm_step_count(connection)

    assert retained_row == ("step-0200", TARGET_PROCESS_ID)
    assert first_row == row_after_growth == ("step-0200",)
    assert all(
        "idx_agent_action_steps_adopted_process" in str(row[3])
        for row in (*prefix_plan, *ordered_plan)
    )
    assert all("TEMP B-TREE" not in str(row[3]) for row in ordered_plan)
    assert grown_vm_steps == baseline_vm_steps
