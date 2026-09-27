from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

from pantaray_agents.local_runtime.memory_catalog.domain_registration import (
    register_inline_domain_memory,
)
from pantaray_agents.local_runtime.runtime import (
    action_legacy_shared_temp_purge as purge_module,
)
from pantaray_agents.local_runtime.runtime.action_legacy_shared_temp_purge import (
    purge_legacy_action_shared_temp_for_startup,
)
from pantaray_agents.local_runtime.runtime.bootstrap import (
    LocalRuntimeBootstrapConfig,
    run_local_runtime_bootstrap,
)
from pantaray_agents.local_runtime.storage.migrations import MigrationError
from pantaray_agents.local_runtime.storage.transactions import immediate_transaction
from pantaray_agents.local_runtime.suggestion_state import public_projection

from . import legacy_action_shared_temp_test_support as support

BUSY_TIMEOUT_MS = 1_000
TIMESTAMP = support.TIMESTAMP


def _seed(tmp_path: Path, *, with_action_memory: bool) -> tuple[Path, Path]:
    db_path, _, fixed_root = support.seed_legacy_shared_temp_action(tmp_path)
    with sqlite3.connect(db_path) as connection, connection:
        connection.row_factory = sqlite3.Row
        connection.execute(
            "UPDATE tool_runtime_resources SET resource_path=? WHERE action_id='action-1'",
            (str(fixed_root),),
        )
        connection.executescript(
            """UPDATE agent_suggestions SET status='success',answer='Keep this',
                 has_suggestion=1,interaction_contract='action_offer',
                 user_reaction='accepted',accepted_at='2026-08-29T00:00:00Z',
                 action_status='success',action_process_id='process-1',
                 action_command_id='command-1',
                 action_started_at='2026-08-29T00:00:00Z'
               WHERE suggestion_id='suggestion-1';
               UPDATE agent_actions SET status='success',final_output='Action done',
                 updated_at='2026-08-29T00:00:00Z' WHERE action_id='action-1';
               INSERT INTO processes(process_id,user_id,kind,status,suggestion_id,
                 action_id,started_at,updated_at,completed_at,heartbeat_at,next_event_seq) VALUES
                 ('process-1','user-1','action','success','suggestion-1','action-1',
                  '2026-08-29T00:00:00Z','2026-08-29T00:00:00Z',
                  '2026-08-29T00:00:00Z','2026-08-29T00:00:00Z',2);
               INSERT INTO jobs(job_id,user_id,job_type,process_id,status,attempt,
                 scheduled_at,started_at,completed_at,logical_key) VALUES
                 ('job-1','user-1','execute_action','process-1','completed',1,
                  '2026-08-29T00:00:00Z','2026-08-29T00:00:00Z',
                  '2026-08-29T00:00:00Z','action-1');
               INSERT INTO job_payloads(job_id,payload_json) VALUES
                 ('job-1',json_object('job_id','job-1','process_id','process-1',
                   'action_id','action-1','user_id','user-1'));
               INSERT INTO job_attempts(attempt_id,job_id,attempt_number,started_at,completed_at,status) VALUES
                 ('attempt-1','job-1',1,'2026-08-29T00:00:00Z',
                  '2026-08-29T00:00:00Z','completed');
               INSERT INTO process_events(process_id,event_seq,event_id,event_name,
                 payload_json,created_at) VALUES
                 ('process-1',1,'process-event','stream_end','{}',
                  '2026-08-29T00:00:00Z');
               INSERT INTO tool_runtime_resource_events(
                 event_id,resource_id,action_id,event_type,message,created_at)
                 SELECT 'resource-event',resource_id,'action-1','cleanup','done',
                   '2026-08-29T00:00:00Z' FROM tool_runtime_resources
                 WHERE action_id='action-1';
               INSERT INTO agent_process_events VALUES
               ('chunk','suggestion-1','user-1',NULL,1,'suggestion_chunk',
                '{"data":{"content":"Keep this"}}','2026-08-29T00:00:00Z'),
               ('suggestion-end','suggestion-1','user-1',NULL,2,'process_completed',
                '{"data":{"kind":"suggestion","status":"success","interaction_contract":"action_offer"}}','2026-08-29T00:00:00Z'),
               ('accepted','suggestion-1','user-1',NULL,3,'suggestion_reaction_committed',
                '{"data":{"reaction":"accepted","committed_at":"2026-08-29T00:00:00Z"}}','2026-08-29T00:00:00Z'),
               ('action-start','suggestion-1','user-1','action-1',4,'process_started',
                '{"data":{"kind":"action","action_id":"action-1","process_id":"process-1","command_id":"command-1"}}','2026-08-29T00:00:00Z'),
               ('action-end','suggestion-1','user-1','action-1',5,'process_completed',
                '{"data":{"kind":"action","status":"success","action_id":"action-1","final_output":"Action done"}}','2026-08-29T00:00:00Z');"""
        )
        public_projection.rebuild_history_projection(
            connection=connection,
            user_id="user-1",
            suggestion_id="suggestion-1",
        )
        if with_action_memory:
            connection.commit()
            with immediate_transaction(connection):
                register_inline_domain_memory(
                    connection=connection,
                    user_id="user-1",
                    source="action",
                    source_record_id="action-1",
                    content="Action done",
                )
    return db_path, fixed_root


@pytest.mark.parametrize("with_action_memory", [True, False])
def test_purge_preserves_suggestion(tmp_path: Path, with_action_memory: bool) -> None:
    db_path, fixed_root = _seed(tmp_path, with_action_memory=with_action_memory)
    if not with_action_memory:
        purge_module.remove_descriptor_confined_directory_child(
            parent_path=fixed_root.parent.parent,
            child_name=fixed_root.parent.name,
        )

    assert (
        purge_legacy_action_shared_temp_for_startup(
            db_path=db_path, busy_timeout_ms=BUSY_TIMEOUT_MS
        )
        == 1
    )

    assert not fixed_root.exists()
    with sqlite3.connect(db_path) as connection:
        action_owned_counts = connection.execute(
            """SELECT
                 (SELECT COUNT(*) FROM agent_actions WHERE action_id='action-1'),
                 (SELECT COUNT(*) FROM agent_action_steps WHERE action_id='action-1'),
                 (SELECT COUNT(*) FROM execution_sessions WHERE action_id='action-1'),
                 (SELECT COUNT(*) FROM tool_runtime_resources WHERE action_id='action-1'),
                 (SELECT COUNT(*) FROM tool_runtime_resource_events WHERE action_id='action-1'),
                 (SELECT COUNT(*) FROM processes WHERE action_id='action-1'),
                 (SELECT COUNT(*) FROM jobs WHERE job_id='job-1'),
                 (SELECT COUNT(*) FROM agent_process_events WHERE action_id='action-1')"""
        ).fetchone()
        suggestion = connection.execute(
            """SELECT answer,user_reaction,accepted_at,action_status,
                      action_process_id,action_command_id,action_started_at
               FROM agent_suggestions WHERE suggestion_id='suggestion-1'"""
        ).fetchone()
        history = connection.execute(
            """SELECT answer,user_reaction,accepted_at,action_status,action_id,
                      final_output,last_sequence
               FROM agent_suggestion_history WHERE suggestion_id='suggestion-1'"""
        ).fetchone()
        purge_receipts = connection.execute(
            """SELECT status,note FROM runtime_recovery_runs
               WHERE note LIKE 'legacy_action_shared_temp_purge;%'
               ORDER BY started_at"""
        ).fetchall()
        memory = connection.execute(
            """SELECT nodes.lifecycle,revisions.body_kind FROM memory_nodes AS nodes
               JOIN memory_revisions AS revisions ON revisions.user_id=nodes.user_id
                 AND revisions.node_id=nodes.node_id AND revisions.revision_id=nodes.current_revision_id
               WHERE nodes.user_id='user-1' AND nodes.source_type='action'
                 AND nodes.source_record_id='action-1'"""
        ).fetchone()
    assert action_owned_counts == (0, 0, 0, 0, 0, 0, 0, 0)
    assert suggestion == ("Keep this", "accepted", TIMESTAMP, None, None, None, None)
    assert history == ("Keep this", "accepted", TIMESTAMP, None, None, None, 3)
    assert purge_receipts == [
        ("completed", "legacy_action_shared_temp_purge; purged_actions=1")
    ]
    assert memory == (("tombstoned", "inline") if with_action_memory else None)

    assert (
        purge_legacy_action_shared_temp_for_startup(
            db_path=db_path, busy_timeout_ms=BUSY_TIMEOUT_MS
        )
        == 0
    )
    with sqlite3.connect(db_path) as connection:
        assert connection.execute(
            """SELECT COUNT(*) FROM runtime_recovery_runs
               WHERE note LIKE 'legacy_action_shared_temp_purge;%'"""
        ).fetchone() == (1,)


def test_post_delete_memory_change_rolls_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_path, fixed_root = _seed(tmp_path, with_action_memory=True)
    original_remove = purge_module.remove_descriptor_confined_directory_child

    def remove_then_change_authority(*, parent_path: Path, child_name: str) -> None:
        original_remove(parent_path=parent_path, child_name=child_name)
        with sqlite3.connect(db_path) as connection, connection:
            connection.execute(
                """UPDATE memory_nodes SET integrity='corrupt'
                   WHERE user_id='user-1' AND source_type='action'
                     AND source_record_id='action-1'"""
            )

    monkeypatch.setattr(
        purge_module,
        "remove_descriptor_confined_directory_child",
        remove_then_change_authority,
    )
    with pytest.raises(MigrationError, match="memory evidence is inconsistent"):
        purge_legacy_action_shared_temp_for_startup(
            db_path=db_path, busy_timeout_ms=BUSY_TIMEOUT_MS
        )

    assert not fixed_root.exists()
    with sqlite3.connect(db_path) as connection:
        assert connection.execute(
            """SELECT
                 EXISTS(SELECT 1 FROM agent_actions WHERE action_id='action-1'),
                 EXISTS(SELECT 1 FROM jobs WHERE job_id='job-1'),
                 NOT EXISTS(SELECT 1 FROM runtime_recovery_runs
                   WHERE note LIKE 'legacy_action_shared_temp_purge;%')"""
        ).fetchone() == (1, 1, 1)


def test_startup_defers_running_agent_experience_until_completion(
    tmp_path: Path,
) -> None:
    db_path, fixed_root = _seed(tmp_path, with_action_memory=False)
    with sqlite3.connect(db_path) as connection, connection:
        connection.execute(
            """INSERT INTO processes(
                   process_id,user_id,kind,status,suggestion_id,action_id,
                   started_at,updated_at,heartbeat_at,current_job_id,next_event_seq)
               VALUES ('process-experience','user-1','agent_experience','running',
                       'suggestion-1','action-1',?,?,?,'job-experience',1)""",
            (TIMESTAMP, TIMESTAMP, TIMESTAMP),
        )
        connection.execute(
            """INSERT INTO jobs(
                   job_id,user_id,job_type,process_id,status,attempt,claimed_by,
                   claimed_at,heartbeat_at,scheduled_at,started_at,logical_key)
               VALUES ('job-experience','user-1','extract_agent_experience',
                       'process-experience','running',1,'worker-1',?,?,?,?,
                       'experience-action-1')""",
            (TIMESTAMP, TIMESTAMP, TIMESTAMP, TIMESTAMP),
        )
        connection.execute(
            """INSERT INTO job_payloads(job_id,payload_json)
               VALUES ('job-experience',json_object(
                   'job_id','job-experience','process_id','process-experience',
                   'action_id','action-1','user_id','user-1',
                   'suggestion_id','suggestion-1'))"""
        )
        connection.execute(
            """INSERT INTO job_attempts(
                   attempt_id,job_id,attempt_number,started_at,status)
               VALUES ('experience-attempt-1','job-experience',1,?,'running')""",
            (TIMESTAMP,),
        )

    config = LocalRuntimeBootstrapConfig(
        db_path=db_path.resolve(),
        busy_timeout_ms=BUSY_TIMEOUT_MS,
        artifact_root=tmp_path / "artifacts",
        app_runtime_python=Path(sys.executable),
    )
    run_local_runtime_bootstrap(
        bootstrap_config=config,
        recovered_runtime_lock_count=0,
        resumed_user_erasure_count=0,
    )

    with sqlite3.connect(db_path) as connection:
        assert connection.execute(
            """SELECT actions.status,jobs.status,processes.status
               FROM agent_actions AS actions
               JOIN jobs ON jobs.job_id='job-experience'
               JOIN processes ON processes.process_id='process-experience'
               WHERE actions.action_id='action-1'"""
        ).fetchone() == ("success", "queued", "enqueued")
        assert (
            purge_legacy_action_shared_temp_for_startup(
                db_path=db_path, busy_timeout_ms=BUSY_TIMEOUT_MS
            )
            == 0
        )
        connection.execute(
            """UPDATE jobs SET status='completed',attempt=2,claimed_by=NULL,
                      claimed_at=NULL,heartbeat_at=NULL,started_at=?,completed_at=?
               WHERE job_id='job-experience'""",
            (TIMESTAMP, TIMESTAMP),
        )
        connection.execute(
            """UPDATE processes SET status='success',current_job_id=NULL,
                      completed_at=?,updated_at=?,heartbeat_at=?
               WHERE process_id='process-experience'""",
            (TIMESTAMP, TIMESTAMP, TIMESTAMP),
        )
        connection.execute(
            """INSERT INTO job_attempts(
                   attempt_id,job_id,attempt_number,started_at,completed_at,status)
               VALUES ('experience-attempt-2','job-experience',2,?,?,'completed')""",
            (TIMESTAMP, TIMESTAMP),
        )
        connection.commit()

    run_local_runtime_bootstrap(
        bootstrap_config=config,
        recovered_runtime_lock_count=0,
        resumed_user_erasure_count=0,
    )

    assert not fixed_root.exists()
    with sqlite3.connect(db_path) as connection:
        assert connection.execute(
            """SELECT
                 EXISTS(SELECT 1 FROM agent_actions WHERE action_id='action-1'),
                 EXISTS(SELECT 1 FROM jobs WHERE job_id='job-experience'),
                 EXISTS(SELECT 1 FROM processes
                        WHERE process_id='process-experience')"""
        ).fetchone() == (0, 0, 0)
