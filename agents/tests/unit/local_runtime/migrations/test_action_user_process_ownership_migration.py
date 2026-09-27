from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from pantaray_agents.local_runtime.storage.migrations import MigrationError
from pantaray_agents.local_runtime.storage.migrations.action_user_process_ownership import (
    create_action_user_process_indexes,
    create_action_user_process_triggers,
)
from pantaray_agents.local_runtime.storage.migrations.connection import (
    configure_connection,
)
from pantaray_agents.schema.agent.action_message import ActionUserMessageInput
from pantaray_agents.tasks.action_user_message import (
    render_action_user_request_text,
    serialize_action_user_message,
)

from .support import (
    _insert_user,
    _migrations_before,
    _migrations_through,
    apply_migrations,
    load_default_migrations,
)

BUSY_TIMEOUT_MS = 1_000
MIGRATION_NAME = "0086_action_user_process_ownership.sql"
TIMESTAMP = "2026-08-29T00:00:00Z"


def _prepare_pre_v86_db(db_path: Path) -> None:
    migrations = _migrations_before(load_default_migrations(), MIGRATION_NAME)
    apply_migrations(db_path, BUSY_TIMEOUT_MS, migrations)
    with sqlite3.connect(db_path) as connection:
        _insert_user(connection, "user-1")


def _insert_action_envelope(
    db_path: Path,
    suffix: str,
) -> tuple[str, str, str, str]:
    action_id = f"action-{suffix}"
    process_id = f"process-{suffix}"
    job_id = f"job-{suffix}"
    user_step_id = f"step-{suffix}"
    message = ActionUserMessageInput(
        message_id=f"message-{suffix}",
        content=f"request message-{suffix}",
    )
    payload = {
        "job_id": job_id,
        "process_id": process_id,
        "action_id": action_id,
        "user_id": "user-1",
        "continuation_ref": {
            "kind": "user_step",
            "user_step_id": user_step_id,
        },
    }
    with sqlite3.connect(db_path) as connection:
        configure_connection(connection, BUSY_TIMEOUT_MS)
        with connection:
            connection.execute(
                """
                INSERT INTO agent_actions(
                    action_id,user_id,initial_user_message_id,execution_target_json,
                    status,final_output,prompt_name,prompt_version,created_at,updated_at
                ) VALUES (?,?,?,'{"kind":"scratch"}','queued','','action','1',?,?)
                """,
                (action_id, "user-1", message.message_id, TIMESTAMP, TIMESTAMP),
            )
            connection.execute(
                """
                INSERT INTO agent_action_steps(
                    step_id,action_id,user_id,step_number,local_step_number,
                    short_step_id,step_type,step_name,status,goal_handle,retry_count,
                    prompt_tokens,completion_tokens,user_message_id,user_message_json,
                    user_request_text,started_at,completed_at,created_at
                ) VALUES (?,?,?,1,1,'S-1-USER','user_request','user_request',
                          'success','S',0,0,0,?,?,?,?,?,?)
                """,
                (
                    user_step_id,
                    action_id,
                    "user-1",
                    message.message_id,
                    serialize_action_user_message(message),
                    render_action_user_request_text(message),
                    TIMESTAMP,
                    TIMESTAMP,
                    TIMESTAMP,
                ),
            )
            connection.execute(
                "INSERT INTO processes(process_id,user_id,kind,status,action_id,"
                "started_at,updated_at,heartbeat_at,next_event_seq) VALUES "
                "(?,?,'action','enqueued',?,?,?,?,1)",
                (process_id, "user-1", action_id, TIMESTAMP, TIMESTAMP, TIMESTAMP),
            )
            connection.execute(
                "INSERT INTO jobs(job_id,user_id,job_type,process_id,status,scheduled_at,"
                "logical_key) VALUES (?,?,'execute_action',?,'queued',?,?)",
                (job_id, "user-1", process_id, TIMESTAMP, action_id),
            )
            connection.execute(
                "INSERT INTO job_payloads(job_id,payload_json) VALUES (?,?)",
                (job_id, json.dumps(payload)),
            )
    return action_id, process_id, job_id, user_step_id


@pytest.mark.parametrize(
    ("process_status", "job_status"),
    (("enqueued", "queued"), ("running", "running"), ("paused", "paused")),
)
def test_v86_backfills_current_claim_and_accepts_expand_window_submission(
    tmp_path: Path,
    process_status: str,
    job_status: str,
) -> None:
    db_path = tmp_path / "runtime.db"
    _prepare_pre_v86_db(db_path)
    _action_id, process_id, job_id, user_step_id = _insert_action_envelope(db_path, "1")
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            "UPDATE processes SET status=? WHERE process_id=?",
            (process_status, process_id),
        )
        connection.execute(
            "UPDATE jobs SET status=? WHERE job_id=?", (job_status, job_id)
        )

    apply_migrations(
        db_path,
        BUSY_TIMEOUT_MS,
        _migrations_through(load_default_migrations(), MIGRATION_NAME),
    )
    expand_ids = _insert_action_envelope(db_path, "2")

    with sqlite3.connect(db_path) as connection:
        configure_connection(connection, BUSY_TIMEOUT_MS)
        backfilled = connection.execute(
            "SELECT accepted_sequence,adopted_process_id FROM agent_action_steps "
            "WHERE step_id=?",
            (user_step_id,),
        ).fetchone()
        expand_row = connection.execute(
            "SELECT step_number,local_step_number,short_step_id,accepted_sequence,"
            "adoption_canceled_at,expected_process_id,adopted_process_id "
            "FROM agent_action_steps WHERE step_id=?",
            (expand_ids[3],),
        ).fetchone()
        violations = connection.execute("PRAGMA foreign_key_check").fetchall()

    assert backfilled == (1, process_id)
    assert expand_row == (1, 1, "S-1-USER", None, None, None, None)
    assert violations == []


def test_v86_preserves_unclaimed_untyped_history(tmp_path: Path) -> None:
    db_path = tmp_path / "runtime.db"
    _prepare_pre_v86_db(db_path)
    with sqlite3.connect(db_path) as connection:
        configure_connection(connection, BUSY_TIMEOUT_MS)
        with connection:
            connection.execute(
                """
                INSERT INTO agent_actions(
                    action_id,user_id,initial_user_message_id,execution_target_json,
                    status,final_output,prompt_name,prompt_version,created_at,updated_at
                ) VALUES ('action-1','user-1','message-1','{"kind":"scratch"}',
                          'success','','action','1',?,?)
                """,
                (TIMESTAMP, TIMESTAMP),
            )
            connection.execute(
                """
                INSERT INTO agent_action_steps(
                    step_id,action_id,user_id,step_number,local_step_number,
                    short_step_id,step_type,step_name,status,goal_handle,
                    user_request_text,created_at
                ) VALUES ('step-1','action-1','user-1',1,1,'S-1-USER',
                          'user_request','request','success','S','legacy',?)
                """,
                (TIMESTAMP,),
            )

    apply_migrations(
        db_path,
        BUSY_TIMEOUT_MS,
        _migrations_through(load_default_migrations(), MIGRATION_NAME),
    )
    with sqlite3.connect(db_path) as connection:
        row = connection.execute(
            "SELECT accepted_sequence,adopted_process_id FROM agent_action_steps"
        ).fetchone()
    assert row == (1, None)


def test_public_ddl_helpers_restore_only_action_step_objects(tmp_path: Path) -> None:
    db_path = tmp_path / "runtime.db"
    _prepare_pre_v86_db(db_path)
    apply_migrations(db_path, BUSY_TIMEOUT_MS, load_default_migrations())
    step_indexes = (
        "idx_agent_action_steps_action_created",
        "idx_agent_action_steps_short_step_id_resolution",
        "idx_agent_action_steps_goal_handle",
        "idx_agent_action_steps_requirement_handle",
        "uq_agent_action_steps_user_message",
        "uq_agent_action_steps_action_accepted_sequence",
        "idx_agent_action_steps_expected_process",
        "idx_agent_action_steps_adopted_process",
    )
    step_triggers = (
        "trg_action_user_process_identity_insert",
        "trg_action_user_process_identity_update",
        "trg_action_user_referenced_process_kind",
    )
    retained_objects = (
        "uq_processes_active_action",
        "uq_jobs_active_action",
    )

    with sqlite3.connect(db_path) as connection:
        configure_connection(connection, BUSY_TIMEOUT_MS)
        retained_before = connection.execute(
            "SELECT type,name,tbl_name,sql FROM sqlite_master "
            "WHERE name IN (?,?) ORDER BY name",
            retained_objects,
        ).fetchall()
        with connection:
            for name in step_indexes:
                connection.execute(f"DROP INDEX {name}")
            for name in step_triggers:
                connection.execute(f"DROP TRIGGER {name}")
            create_action_user_process_indexes(connection)
            create_action_user_process_triggers(connection)
        restored = connection.execute(
            "SELECT name FROM sqlite_master "
            "WHERE name IN (?,?,?,?,?,?,?,?,?,?,?) "
            "ORDER BY name",
            (*step_indexes, *step_triggers),
        ).fetchall()
        retained_after = connection.execute(
            "SELECT type,name,tbl_name,sql FROM sqlite_master "
            "WHERE name IN (?,?) ORDER BY name",
            retained_objects,
        ).fetchall()

    assert [row[0] for row in restored] == sorted((*step_indexes, *step_triggers))
    assert len(retained_before) == len(retained_objects)
    assert retained_after == retained_before


def test_v86_rolls_back_ambiguous_lineage(tmp_path: Path) -> None:
    db_path = tmp_path / "runtime.db"
    _prepare_pre_v86_db(db_path)
    action_id, _process_id, _job_id, user_step_id = _insert_action_envelope(
        db_path, "1"
    )
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            "INSERT INTO processes(process_id,user_id,kind,status,action_id,started_at,"
            "updated_at,heartbeat_at,next_event_seq) VALUES "
            "('process-2','user-1','action','completed',?,?,?, ?,1)",
            (action_id, TIMESTAMP, TIMESTAMP, TIMESTAMP),
        )
        connection.execute(
            "INSERT INTO jobs(job_id,user_id,job_type,process_id,status,scheduled_at,"
            "logical_key) VALUES ('job-2','user-1','execute_action','process-2',"
            "'completed',?,?)",
            (TIMESTAMP, action_id),
        )
        payload = {
            "job_id": "job-2",
            "process_id": "process-2",
            "action_id": action_id,
            "user_id": "user-1",
            "continuation_ref": {
                "kind": "user_step",
                "user_step_id": user_step_id,
            },
        }
        connection.execute(
            "INSERT INTO job_payloads(job_id,payload_json) VALUES ('job-2',?)",
            (json.dumps(payload),),
        )

    with pytest.raises(MigrationError, match="multiple process claims"):
        apply_migrations(db_path, BUSY_TIMEOUT_MS, load_default_migrations())
    with sqlite3.connect(db_path) as connection:
        version = connection.execute(
            "SELECT current_version FROM schema_versions WHERE component='local_runtime'"
        ).fetchone()
        columns = tuple(
            row[1]
            for row in connection.execute("PRAGMA table_info(agent_action_steps)")
        )
        index = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE name='uq_processes_user_action_process'"
        ).fetchone()
    assert version == (85,)
    assert "accepted_sequence" not in columns
    assert index is None


def test_v86_enforces_user_ownership_and_active_fences(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "runtime.db"
    _prepare_pre_v86_db(db_path)
    action_id, process_id, _job_id, user_step_id = _insert_action_envelope(db_path, "1")
    apply_migrations(db_path, BUSY_TIMEOUT_MS, load_default_migrations())

    with sqlite3.connect(db_path) as connection:
        configure_connection(connection, BUSY_TIMEOUT_MS)
        connection.execute(
            "UPDATE agent_action_steps SET accepted_sequence=1 WHERE step_id=?",
            (user_step_id,),
        )
        connection.execute(
            "INSERT INTO agent_action_steps(step_id,action_id,user_id,step_type,"
            "step_name,status,goal_handle,user_request_text,created_at,"
            "accepted_sequence,expected_process_id) VALUES "
            "('step-pending',?,'user-1','user_request','request','success','S',"
            "'pending',?,2,?)",
            (action_id, TIMESTAMP, process_id),
        )
        connection.commit()

        def reject(sql: str, parameters: tuple[object, ...] = ()) -> None:
            with pytest.raises(sqlite3.IntegrityError):
                connection.execute(sql, parameters)

        reject(
            "UPDATE agent_action_steps SET adopted_process_id=NULL WHERE step_id=?",
            (user_step_id,),
        )
        reject(
            "UPDATE agent_action_steps SET expected_process_id=NULL "
            "WHERE step_id='step-pending'"
        )
        reject(
            "UPDATE processes SET kind='insight' WHERE process_id=?",
            (process_id,),
        )
        reject("DELETE FROM processes WHERE process_id=?", (process_id,))
        reject(
            "UPDATE agent_action_steps SET adoption_canceled_at=? WHERE step_id=?",
            (TIMESTAMP, user_step_id),
        )
        for value in ("invalid", 3):
            reject(
                "UPDATE agent_action_steps SET accepted_sequence=? WHERE step_id='step-pending'",
                (value,),
            )
        reject(
            "INSERT INTO agent_action_steps(step_id,action_id,user_id,step_type,"
            "step_name,status,goal_handle,user_request_text,created_at,"
            "accepted_sequence) VALUES ('step-duplicate',?,'user-1','user_request',"
            "'request','success','S','duplicate',?,1)",
            (action_id, TIMESTAMP),
        )
        reject(
            "INSERT INTO processes(process_id,user_id,kind,status,action_id,started_at,"
            "updated_at,heartbeat_at,next_event_seq) VALUES ('process-2','user-1',"
            "'action','running',?,?,?, ?,1)",
            (action_id, TIMESTAMP, TIMESTAMP, TIMESTAMP),
        )
        reject(
            "INSERT INTO jobs(job_id,user_id,job_type,status,scheduled_at,logical_key) "
            "VALUES ('job-2','user-1','execute_action','retryable_error',?,?)",
            (TIMESTAMP, action_id),
        )
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
