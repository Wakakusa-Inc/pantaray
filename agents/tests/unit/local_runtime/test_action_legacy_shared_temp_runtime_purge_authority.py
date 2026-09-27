from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from pantaray_agents.local_runtime.runtime.action_legacy_shared_temp_runtime_purge_authority import (
    list_legacy_action_shared_temp_runtime_purge_authorities_in_connection,
)
from pantaray_agents.local_runtime.storage.migrations import MigrationError

from .legacy_action_shared_temp_test_support import (
    TIMESTAMP,
    seed_legacy_shared_temp_action,
)


def _seed(tmp_path: Path) -> Path:
    db_path, _, fixed_root = seed_legacy_shared_temp_action(tmp_path)
    # fmt: off
    processes = (
        ("pa", "action", "completed", TIMESTAMP, TIMESTAMP, TIMESTAMP, TIMESTAMP),
        ("pe", "agent_experience", "enqueued", TIMESTAMP, TIMESTAMP, None, TIMESTAMP),
        ("pr", "post_action_pipeline", "canceled", TIMESTAMP, TIMESTAMP, TIMESTAMP, TIMESTAMP),
    )
    jobs = (
        ("ja", "execute_action", "pa", "completed", 1, TIMESTAMP, "action-1"),
        ("je", "extract_agent_experience", "pe", "queued", 0, None, "je"),
        ("jr", "post_action_pipeline", "pr", "canceled", 0, TIMESTAMP, "action-1"),
    )
    # fmt: on
    with sqlite3.connect(db_path) as connection, connection:
        connection.executemany(
            """INSERT INTO processes(process_id,user_id,kind,status,suggestion_id,action_id,started_at,updated_at,completed_at,heartbeat_at,next_event_seq) VALUES (?,'user-1',?,?,'suggestion-1','action-1',?,?,?,?,2)""",
            processes,
        )
        connection.executemany(
            """INSERT INTO jobs(job_id,user_id,job_type,process_id,status,attempt,scheduled_at,completed_at,logical_key) VALUES (?,'user-1',?,?,?,?,?,?,?)""",
            tuple((*row[:5], TIMESTAMP, row[5], row[6]) for row in jobs),
        )
        connection.executemany(
            """INSERT INTO job_payloads(job_id,payload_json) VALUES (?,json_patch(json_object('job_id',?,'process_id',?,'action_id','action-1','user_id','user-1'),CASE ?
               WHEN 'ja' THEN json_object('continuation_ref',json_object('kind','user_step','user_step_id','user-step-1'))
               WHEN 'je' THEN json_object('suggestion_id','suggestion-1','action_completed_at','2026-08-29T00:00:00Z','source_action_revision_id','revision-1','turn_start_step_number',1,'turn_end_step_number',1,'action_prompt_name','action/executing','action_prompt_version','1.0','enqueued_at','2026-08-29T00:00:00Z')
               ELSE json_object('suggestion_id','suggestion-1','action_completed_at','2026-08-29T00:00:00Z','expected_period_end_1','2026-08-29T00:04:00Z','expected_period_end_2','2026-08-29T00:08:00Z','deadline_at','2026-08-29T00:10:00Z','scheduled_at','2026-08-29T00:08:05Z','enqueued_at','2026-08-29T00:00:00Z') END))""",
            tuple((row[0], row[0], row[2], row[0]) for row in jobs),
        )
        connection.execute(
            """INSERT INTO job_attempts(attempt_id,job_id,attempt_number,started_at,completed_at,status) VALUES ('attempt-1','ja',1,?,?,'completed')""",
            (TIMESTAMP, TIMESTAMP),
        )
        connection.executemany(
            """INSERT INTO process_events(process_id,event_seq,event_id,event_name,payload_json,created_at) VALUES (?,1,?,'stream_end','{}',?)""",
            tuple((row[0], f"event-{row[0]}", TIMESTAMP) for row in processes),
        )
        connection.execute(
            "UPDATE tool_runtime_resources SET resource_path=? WHERE action_id='action-1'",
            (str(fixed_root),),
        )
        connection.execute(
            """INSERT INTO tool_runtime_resource_events(event_id,resource_id,action_id,event_type,message,created_at) SELECT 'resource-event',resource_id,'action-1','cleanup','done',? FROM tool_runtime_resources
                   WHERE action_id='action-1'""",
            (TIMESTAMP,),
        )
        connection.execute(
            """INSERT INTO agent_process_events(event_id,user_id,action_id,sequence,event_name,payload,created_at)
               VALUES ('public-event','user-1','action-1',1,'action_summary','{}',?)""",
            (TIMESTAMP,),
        )
    return db_path


def _load(db_path: Path):
    resolved = db_path.resolve()
    with sqlite3.connect(f"{resolved.as_uri()}?mode=ro", uri=True) as connection:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only=ON")
        connection.execute("BEGIN")
        return list_legacy_action_shared_temp_runtime_purge_authorities_in_connection(
            connection=connection, resolved_db_path=resolved
        )


def test_complete_inventory_includes_current_and_retired(tmp_path: Path) -> None:
    authority = _load(_seed(tmp_path))[0]

    assert [(row.process.kind, row.process.status) for row in authority.processes] == [
        ("action", "completed"),
        ("agent_experience", "enqueued"),
        ("post_action_pipeline", "canceled"),
    ]
    assert sum(len(row.jobs) for row in authority.processes) == 3
    assert sum(len(row.events) for row in authority.processes) == 3
    assert authority.processes[0].jobs[0].attempts[0].attempt_id == "attempt-1"
    assert authority.resource_events[0].event_id == "resource-event"
    assert authority.action_public_events[0].event_id == "public-event"


def test_payload_owner_mismatch_is_rejected(tmp_path: Path) -> None:
    db_path = _seed(tmp_path)
    with sqlite3.connect(db_path) as connection, connection:
        connection.execute(
            """UPDATE job_payloads
               SET payload_json=json_set(payload_json,'$.user_id','user-2')
               WHERE job_id='ja'"""
        )

    with pytest.raises(MigrationError, match="payload ownership"):
        _load(db_path)
