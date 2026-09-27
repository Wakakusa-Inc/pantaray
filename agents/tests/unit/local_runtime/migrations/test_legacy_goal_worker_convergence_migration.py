from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from pantaray_agents.local_runtime.runtime.action_message_process_fence import (
    resolve_action_process_lineage_in_connection,
)
from pantaray_agents.local_runtime.runtime.job_payload_builder import (
    build_action_job_payload,
)
from pantaray_agents.local_runtime.storage.migrations import (
    MigrationError,
    repair_inflight_jobs_for_startup,
)
from pantaray_agents.local_runtime.storage.migrations.connection import (
    configure_connection,
)

from .support import (
    _insert_user,
    _migrations_before,
    apply_migrations,
    load_default_migrations,
)

MIGRATION_NAME = "0085_legacy_goal_worker_convergence.sql"
BUSY_TIMEOUT_MS = 1_000
USER_ID = "user-legacy"
ACTION_ID = "action-legacy"
PROCESS_ID = "process-legacy"
JOB_ID = "job-legacy"
SUGGESTION_ID = "suggestion-legacy"
TIMESTAMP = "2026-08-28T00:00:00Z"


def _seed_action(
    db_path: Path,
    *,
    checkpoint_values: tuple[object, ...] = (True,),
    action_status: str = "processing",
    runtime_status: str | None = None,
    linked: bool = True,
    initial_message_id: str = "message-initial",
    command_id: str = "message-followup",
    continuation_kind: str = "user_step",
    persist_payload: bool = True,
    process_status_override: str | None = None,
    new_user_turn: bool = False,
) -> None:
    migrations = load_default_migrations()
    apply_migrations(
        db_path,
        BUSY_TIMEOUT_MS,
        _migrations_before(migrations, MIGRATION_NAME),
    )
    job_status = runtime_status or (
        "running" if action_status == "processing" else "queued"
    )
    process_status = (
        process_status_override
        or {
            "queued": "enqueued",
            "running": "running",
            "paused": "paused",
            "blocked": "enqueued",
        }[job_status]
    )
    process_is_started = job_status == "running" or process_status == "abandoned"
    job_started_at = TIMESTAMP if process_is_started else None
    process_completed_at = TIMESTAMP if process_status == "abandoned" else None
    suggestion_id = SUGGESTION_ID if linked else None
    with sqlite3.connect(db_path) as connection, connection:
        configure_connection(connection, BUSY_TIMEOUT_MS)
        _insert_user(connection, USER_ID)
        if linked:
            connection.execute(
                "INSERT INTO agent_suggestions(suggestion_id,user_id,status,answer,prompt_name,prompt_version,has_suggestion,interaction_contract,accepted_at,action_started_at,action_status,action_command_id,action_process_id,created_at,updated_at) VALUES (?,?,'success','Legacy work','suggestion','1',1,'action_offer','old-accepted','old-started','processing','old-command','old-process',?,?)",
                (SUGGESTION_ID, USER_ID, TIMESTAMP, TIMESTAMP),
            )
        connection.execute("INSERT INTO agent_actions(action_id,user_id,suggestion_id,initial_user_message_id,execution_target_json,status,final_output,prompt_name,prompt_version,total_steps,total_llm_steps,total_tool_steps,total_prompt_tokens,total_completion_tokens,total_tokens,created_at,updated_at) VALUES (?,?,?,?,'{\"kind\":\"scratch\"}',?,'','action/executing','1',5,3,2,80,20,100,?,?)", (ACTION_ID, USER_ID, suggestion_id, initial_message_id, action_status, TIMESTAMP, TIMESTAMP))  # fmt: skip
        connection.execute("INSERT INTO processes(process_id,user_id,kind,status,suggestion_id,action_id,started_at,updated_at,completed_at,heartbeat_at,current_job_id,next_event_seq) VALUES (?,?,'action',?,?,?,?,?,?,?,?,1)", (PROCESS_ID, USER_ID, process_status, suggestion_id, ACTION_ID, TIMESTAMP, TIMESTAMP, process_completed_at, TIMESTAMP, JOB_ID if job_status == "running" else None))  # fmt: skip
        connection.execute("INSERT INTO jobs(job_id,user_id,job_type,logical_key,process_id,status,attempt,scheduled_at,started_at,heartbeat_at) VALUES (?,?,'execute_action',?,?,?,?,?,?,?)", (JOB_ID, USER_ID, ACTION_ID, PROCESS_ID, job_status, int(job_status == "running"), TIMESTAMP, job_started_at, TIMESTAMP if job_status == "running" else None))  # fmt: skip
        user_step_number = len(checkpoint_values) + 2 if new_user_turn else 1
        message_json = f'{{"version":1,"message_id":"{command_id}","content":"{command_id}","images":[]}}'
        connection.execute("INSERT INTO agent_action_steps(step_id,action_id,user_id,step_number,local_step_number,short_step_id,step_type,step_name,status,goal_handle,user_request_text,user_message_id,user_message_json,started_at,completed_at,created_at) VALUES ('user-step-current',?,?,?,?,?,'user_request','user_request','success','S',?,?,?,?,?,?)", (ACTION_ID, USER_ID, user_step_number, user_step_number, f"S-{user_step_number}-USER", command_id, command_id, message_json, TIMESTAMP, TIMESTAMP, TIMESTAMP))  # fmt: skip
        if persist_payload:
            continuation_ref = (
                {"kind": "user_step", "user_step_id": "user-step-current"}
                if continuation_kind == "user_step"
                else {
                    "kind": "tool_approval",
                    "approval_session_id": "approval-decided",
                    "tool_request_id": "request-decided",
                }
            )
            connection.execute(
                "INSERT INTO job_payloads(job_id, payload_json) VALUES (?, ?)",
                (
                    JOB_ID,
                    json.dumps(
                        build_action_job_payload(
                            {
                                "job_id": JOB_ID,
                                "process_id": PROCESS_ID,
                                "action_id": ACTION_ID,
                                "user_id": USER_ID,
                                "continuation_ref": continuation_ref,
                            }
                        )
                    ),
                ),
            )
        for index, value in enumerate(checkpoint_values, start=2):
            status = "processing" if index == len(checkpoint_values) + 1 else "success"
            checkpoint_json = f'{{"context":{{"use_goal_workers":{json.dumps(value)}}},"steps_taken":7,"llm_steps_taken":4,"tool_steps_taken":3,"total_prompt_tokens":111,"total_completion_tokens":22}}'
            connection.execute("INSERT INTO agent_action_steps(step_id,action_id,user_id,step_number,local_step_number,short_step_id,step_type,step_name,status,runtime_state_checkpoint,runtime_state_checkpoint_version,started_at,created_at) VALUES (?,?,?,?,?,?,'llm_output','thinking',?,?,4,?,?)", (f"checkpoint-{index}", ACTION_ID, USER_ID, index, index, f"S-{index}-THINK", status, checkpoint_json, TIMESTAMP, TIMESTAMP))  # fmt: skip
        if job_status == "running":
            connection.execute("INSERT INTO job_attempts(attempt_id,job_id,attempt_number,started_at,status) VALUES ('attempt-legacy',?,1,?,'running')", (JOB_ID, TIMESTAMP))  # fmt: skip


def _insert_active_tool_rows(db_path: Path) -> None:
    with sqlite3.connect(db_path) as connection, connection:
        connection.executescript(
            f"""
            INSERT INTO execution_sessions(execution_session_id,user_id,action_id,exec_mode,cwd_path,network_policy,capability_snapshot_json,status,started_at) VALUES ('session-legacy','{USER_ID}','{ACTION_ID}','brokered_file_ops','.','cloud-proxy-only','{{}}','running','{TIMESTAMP}');
            INSERT INTO tool_definitions(tool_id,tool_name,tool_description,category,risk_level,input_schema_json,is_enabled,version,created_at,updated_at) VALUES ('tool-legacy','Tool','Tool','editor','medium','{{}}',1,'1','{TIMESTAMP}','{TIMESTAMP}');
            INSERT INTO tool_invocations(invocation_id,user_id,action_id,tool_id,execution_session_id,intent_class,started_at,status) VALUES ('invocation-legacy','{USER_ID}','{ACTION_ID}','tool-legacy','session-legacy','surgical_edit','{TIMESTAMP}','running');
            INSERT INTO approval_sessions(approval_session_id,user_id,action_id,tool_request_id,tool_id,intent_class,approval_source,status,approved_capabilities_json,command_summary_json,requested_at,created_at) VALUES ('approval-legacy','{USER_ID}','{ACTION_ID}','request-legacy','tool-legacy','surgical_edit','prompt','pending','[]','{{}}','{TIMESTAMP}','{TIMESTAMP}');
            """
        )


def _apply_v85(db_path: Path) -> None:
    apply_migrations(db_path, BUSY_TIMEOUT_MS, load_default_migrations())


@pytest.mark.parametrize(
    ("continuation_kind", "runtime_status", "persist_payload"),
    [
        ("user_step", "running", True),
        ("tool_approval", "queued", True),
        ("tool_approval", "running", True),
        ("tool_approval", "running", False),
    ],
)
def test_v85_converges_linked_action_and_active_runtime(
    tmp_path: Path,
    continuation_kind: str,
    runtime_status: str,
    persist_payload: bool,
) -> None:
    db_path = tmp_path / "runtime.db"
    _seed_action(
        db_path,
        continuation_kind=continuation_kind,
        runtime_status=runtime_status,
        persist_payload=persist_payload,
    )
    _insert_active_tool_rows(db_path)
    _apply_v85(db_path)
    assert repair_inflight_jobs_for_startup(db_path, BUSY_TIMEOUT_MS) == 0

    with sqlite3.connect(db_path) as connection:
        action = connection.execute("SELECT status,error,total_steps,total_llm_steps,total_tool_steps,total_prompt_tokens,total_completion_tokens,total_tokens FROM agent_actions WHERE action_id=?", (ACTION_ID,)).fetchone()  # fmt: skip
        suggestion = connection.execute("SELECT accepted_at,action_started_at,action_status,action_command_id,action_process_id,action_failure_code,action_failure_stage FROM agent_suggestions WHERE suggestion_id=?", (SUGGESTION_ID,)).fetchone()  # fmt: skip
        statuses = connection.execute("SELECT jobs.status,attempts.status,processes.status FROM jobs LEFT JOIN job_attempts AS attempts USING(job_id) JOIN processes USING(process_id) WHERE jobs.job_id=?", (JOB_ID,)).fetchone()  # fmt: skip
        owned = connection.execute("SELECT approvals.status,tools.status,sessions.status FROM approval_sessions AS approvals JOIN tool_invocations AS tools USING(action_id) JOIN execution_sessions AS sessions USING(action_id) WHERE approvals.action_id=?", (ACTION_ID,)).fetchone()  # fmt: skip
        events = connection.execute("SELECT (SELECT event_name FROM process_events WHERE process_id=?),public.event_name,public.payload FROM agent_process_events AS public WHERE public.action_id=?", (PROCESS_ID, ACTION_ID)).fetchone()  # fmt: skip
        history = connection.execute("SELECT action_failure_code,action_failure_stage FROM agent_suggestion_history WHERE suggestion_id=?", (SUGGESTION_ID,)).fetchone()  # fmt: skip
        active_step_count = connection.execute("SELECT COUNT(*) FROM agent_action_steps WHERE action_id=? AND status IN ('queued','processing')", (ACTION_ID,)).fetchone()[0]  # fmt: skip
        connection.row_factory = sqlite3.Row
        lineage = resolve_action_process_lineage_in_connection(
            connection=connection,
            user_id=USER_ID,
            action_id=ACTION_ID,
            process_id=PROCESS_ID,
        )
    assert action is not None and action[0] == "error"
    assert json.loads(str(action[1]))["error_code"] == (
        "ACTION_ORCHESTRATION_MODE_RETIRED"
    )
    assert action[2:] == (7, 4, 3, 111, 22, 133)
    assert suggestion == (
        TIMESTAMP,
        "old-started",
        "error",
        "message-followup",
        PROCESS_ID,
        "ACTION_ORCHESTRATION_MODE_RETIRED",
        "resume_failed",
    )
    assert statuses == (
        "failed",
        "failed" if runtime_status == "running" else None,
        "failed",
    )
    assert owned == ("interrupted", "canceled", "canceled")
    assert events[:2] == ("stream_end", "process_completed")
    assert json.loads(str(events[2]))["data"]["command_id"] == "message-followup"
    assert history == ("ACTION_ORCHESTRATION_MODE_RETIRED", "resume_failed")
    assert active_step_count == 0
    assert lineage.root_process_id == PROCESS_ID
    assert lineage.root_accepted_sequence == 1


@pytest.mark.parametrize(
    ("action_status", "runtime_status"),
    [("queued", "queued"), ("processing", "running")],
)
def test_v85_preserves_new_user_turn_after_legacy_checkpoint(
    tmp_path: Path, action_status: str, runtime_status: str
) -> None:
    db_path = tmp_path / "runtime.db"
    _seed_action(
        db_path,
        action_status=action_status,
        runtime_status=runtime_status,
        new_user_turn=True,
    )

    _apply_v85(db_path)

    with sqlite3.connect(db_path) as connection:
        state = connection.execute("SELECT actions.status,jobs.status,processes.status,(SELECT COUNT(*) FROM process_events WHERE event_id LIKE 'v85-%') FROM agent_actions AS actions JOIN jobs ON jobs.logical_key=actions.action_id JOIN processes USING(process_id)").fetchone()  # fmt: skip
    expected_process_status = "running" if runtime_status == "running" else "enqueued"
    assert state == (action_status, runtime_status, expected_process_status, 0)


@pytest.mark.parametrize(
    ("runtime_status", "process_status"),
    [
        ("paused", None),
        ("blocked", None),
        ("blocked", "abandoned"),
    ],
)
def test_v85_converges_nonrunning_standalone_action_with_first_public_event(
    tmp_path: Path,
    runtime_status: str,
    process_status: str | None,
) -> None:
    db_path = tmp_path / "runtime.db"
    _seed_action(
        db_path,
        action_status="processing",
        runtime_status=runtime_status,
        linked=False,
        persist_payload=runtime_status != "blocked",
        process_status_override=process_status,
    )

    _apply_v85(db_path)

    with sqlite3.connect(db_path) as connection:
        statuses = connection.execute("SELECT actions.status,jobs.status,processes.status,actions.total_steps,actions.total_llm_steps,actions.total_tool_steps,actions.total_prompt_tokens,actions.total_completion_tokens,actions.total_tokens FROM agent_actions AS actions JOIN jobs ON jobs.logical_key=actions.action_id JOIN processes ON processes.process_id=jobs.process_id WHERE actions.action_id=?", (ACTION_ID,)).fetchone()  # fmt: skip
        event = connection.execute("SELECT suggestion_id,action_id,sequence,event_name FROM agent_process_events WHERE action_id=?", (ACTION_ID,)).fetchone()  # fmt: skip
    assert statuses == ("error", "failed", "failed", 7, 4, 3, 111, 22, 133)
    assert event == (None, ACTION_ID, 1, "process_completed")


@pytest.mark.parametrize(
    "corruption_sql",
    [
        "UPDATE agent_action_steps SET runtime_state_checkpoint=json_set(runtime_state_checkpoint,'$.steps_taken',json('true')) WHERE runtime_state_checkpoint IS NOT NULL",
        "UPDATE agent_action_steps SET runtime_state_checkpoint=json_set(runtime_state_checkpoint,'$.steps_taken',8) WHERE runtime_state_checkpoint IS NOT NULL",
        "UPDATE agent_actions SET total_steps=8 WHERE action_id='action-legacy'",
    ],
)
def test_v85_rejects_invalid_or_regressing_checkpoint_counters(
    tmp_path: Path, corruption_sql: str
) -> None:
    db_path = tmp_path / "runtime.db"
    _seed_action(db_path)
    with sqlite3.connect(db_path) as connection, connection:
        connection.execute(corruption_sql)

    with pytest.raises(MigrationError, match="checkpoint"):
        _apply_v85(db_path)

    with sqlite3.connect(db_path) as connection:
        state = connection.execute("SELECT status,(SELECT current_version FROM schema_versions WHERE component='local_runtime') FROM agent_actions WHERE action_id=?", (ACTION_ID,)).fetchone()  # fmt: skip
    assert state == ("processing", 84)


@pytest.mark.parametrize(
    ("values", "status"),
    [
        ((False,), "processing"),
        ((1,), "processing"),
        (("true",), "processing"),
        ((True, False), "processing"),
        ((True,), "success"),
    ],
)
def test_v85_only_selects_latest_exact_true_nonterminal_checkpoint(
    tmp_path: Path,
    values: tuple[object, ...],
    status: str,
) -> None:
    db_path = tmp_path / "runtime.db"
    _seed_action(db_path, checkpoint_values=values, action_status=status)

    _apply_v85(db_path)

    with sqlite3.connect(db_path) as connection:
        row = connection.execute("SELECT status, error FROM agent_actions WHERE action_id=?", (ACTION_ID,)).fetchone()  # fmt: skip
    assert row == (status, None)


def test_v85_does_not_select_cross_owner_checkpoint(tmp_path: Path) -> None:
    db_path = tmp_path / "runtime.db"
    _seed_action(db_path, checkpoint_values=(False,))

    with sqlite3.connect(db_path) as connection, connection:
        _insert_user(connection, "user-other")
        connection.execute("INSERT INTO agent_action_steps(step_id,action_id,user_id,step_number,local_step_number,short_step_id,step_type,step_name,status,runtime_state_checkpoint,runtime_state_checkpoint_version,started_at,created_at) VALUES ('checkpoint-other',?,'user-other',99,99,'S-99-THINK','llm_output','thinking','processing',?,4,?,?)", (ACTION_ID, json.dumps({"context": {"use_goal_workers": True}}), TIMESTAMP, TIMESTAMP))  # fmt: skip

    _apply_v85(db_path)

    with sqlite3.connect(db_path) as connection:
        status = connection.execute("SELECT status FROM agent_actions WHERE action_id=?", (ACTION_ID,)).fetchone()[0]  # fmt: skip
    assert status == "processing"


def test_v85_rejects_blocked_job_without_verified_process(tmp_path: Path) -> None:
    db_path = tmp_path / "runtime.db"
    _seed_action(
        db_path,
        runtime_status="blocked",
        linked=False,
        persist_payload=False,
    )
    with sqlite3.connect(db_path) as connection, connection:
        connection.execute("UPDATE jobs SET process_id=NULL WHERE job_id=?", (JOB_ID,))

    with pytest.raises(MigrationError, match="runtime lineage is inconsistent"):
        _apply_v85(db_path)

    with sqlite3.connect(db_path) as connection:
        state = connection.execute("SELECT actions.status,jobs.status,(SELECT current_version FROM schema_versions WHERE component='local_runtime') FROM agent_actions AS actions JOIN jobs ON jobs.logical_key=actions.action_id").fetchone()  # fmt: skip
    assert state == ("processing", "blocked", 84)


def test_v85_rolls_back_all_updates_on_projection_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from pantaray_agents.local_runtime.suggestion_state import (
        public_projection,
    )

    db_path = tmp_path / "runtime.db"
    _seed_action(db_path)

    def _fail_projection(**_kwargs: object) -> None:
        raise RuntimeError("projection failed")

    monkeypatch.setattr(
        public_projection,
        "rebuild_history_projection",
        _fail_projection,
    )
    with pytest.raises(MigrationError, match=MIGRATION_NAME):
        _apply_v85(db_path)

    with sqlite3.connect(db_path) as connection:
        state = connection.execute("SELECT actions.status,jobs.status,(SELECT COUNT(*) FROM process_events WHERE event_id LIKE 'v85-%'),(SELECT current_version FROM schema_versions WHERE component='local_runtime') FROM agent_actions AS actions JOIN jobs ON jobs.logical_key=actions.action_id").fetchone()  # fmt: skip
    assert state == ("processing", "running", 0, 84)
