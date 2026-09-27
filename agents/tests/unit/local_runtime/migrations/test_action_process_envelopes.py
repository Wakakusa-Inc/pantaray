from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from pantaray_agents.local_runtime.storage.migrations import MigrationError
from pantaray_agents.local_runtime.storage.migrations.action_process_envelopes import (
    ActionProcessEnvelope,
    load_action_process_envelopes,
)
from pantaray_agents.local_runtime.storage.migrations.connection import (
    configure_connection,
)

from .support import _insert_user, apply_migrations, load_default_migrations

BUSY_TIMEOUT_MS = 1_000
TIMESTAMP = "2026-08-29T00:00:00Z"
V85_TIMESTAMP = "2026-08-29T00:00:00.000Z"
COUNTERFEIT_V85_TIMESTAMP = "2026-08-29T09:00:00.000+09:00"
NAIVE_TIMESTAMP = "2000-01-01T00:00:00"
INVALID_TIMESTAMP = "2026-02-30T00:00:00Z"
V85_FAILURE_CODE = "ACTION_ORCHESTRATION_MODE_RETIRED"
V85_MIGRATION_NAME = "0085_legacy_goal_worker_convergence.sql"


@pytest.fixture
def connection(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    db_path = tmp_path / "runtime.db"
    apply_migrations(db_path, BUSY_TIMEOUT_MS, load_default_migrations())
    active_connection = sqlite3.connect(db_path)
    configure_connection(active_connection, BUSY_TIMEOUT_MS)
    yield active_connection
    active_connection.close()


def _expect_error(connection: sqlite3.Connection, pattern: str) -> None:
    connection.execute("PRAGMA query_only = ON")
    with pytest.raises(MigrationError, match=pattern):
        load_action_process_envelopes(connection)


def _insert_scope(connection: sqlite3.Connection) -> None:
    _insert_user(connection, "user-1")
    _insert_user(connection, "user-2")
    connection.executemany(
        "INSERT INTO agent_actions(action_id,user_id,initial_user_message_id,"
        "execution_target_json,status,final_output,prompt_name,prompt_version,"
        'created_at,updated_at) VALUES (?,?,?,\'{"kind":"scratch"}\','
        "'processing','','action','1',?,?)",
        (
            ("action-1", "user-1", "message-1", TIMESTAMP, TIMESTAMP),
            ("action-2", "user-2", "message-2", TIMESTAMP, TIMESTAMP),
        ),
    )


def _insert_action_process(
    connection: sqlite3.Connection,
    suffix: str,
    *,
    continuation_kind: str = "user_step",
) -> ActionProcessEnvelope:
    process_id = f"process-{suffix}"
    job_id = f"job-{suffix}"
    connection.execute(
        "INSERT INTO processes(process_id,user_id,kind,status,action_id,"
        "started_at,updated_at,heartbeat_at,next_event_seq) VALUES "
        "(?,'user-1','action','completed','action-1',?,?,?,1)",
        (process_id, TIMESTAMP, TIMESTAMP, TIMESTAMP),
    )
    connection.execute(
        "INSERT INTO jobs(job_id,user_id,job_type,process_id,status,scheduled_at,"
        "logical_key) VALUES (?,'user-1','execute_action',?,'completed',?,'action-1')",
        (job_id, process_id, TIMESTAMP),
    )
    continuation = (
        {"kind": "user_step", "user_step_id": f"step-{suffix}"}
        if continuation_kind == "user_step"
        else {
            "kind": continuation_kind,
            "approval_session_id": f"approval-{suffix}",
            "tool_request_id": f"tool-{suffix}",
        }
    )
    payload = {
        "job_id": job_id,
        "process_id": process_id,
        "action_id": "action-1",
        "user_id": "user-1",
        "continuation_ref": continuation,
    }
    connection.execute(
        "INSERT INTO job_payloads(job_id,payload_json) VALUES (?,?)",
        (job_id, json.dumps(payload)),
    )
    user_step_id = f"step-{suffix}" if continuation_kind == "user_step" else None
    return ActionProcessEnvelope(
        job_id, process_id, "action-1", "user-1", user_step_id, None
    )


def _certify_v85_lineage(
    connection: sqlite3.Connection,
    suffix: str,
    *,
    command_id: str = "message-1",
) -> None:
    process_id = f"process-{suffix}"
    event_id = f"v85-legacy-goal-worker-internal:{process_id}"
    error = {
        "error_code": V85_FAILURE_CODE,
        "error_type": "resume_error",
        "error_message": "Action execution failed.",
        "severity": "error",
    }
    connection.execute(
        "UPDATE jobs SET status='failed',error_code=?,completed_at=? WHERE job_id=?",
        (V85_FAILURE_CODE, V85_TIMESTAMP, f"job-{suffix}"),
    )
    connection.execute(
        "UPDATE processes SET status='failed',terminal_event_id=?,completed_at=? "
        "WHERE process_id=?",
        (event_id, V85_TIMESTAMP, process_id),
    )
    connection.execute(
        "UPDATE agent_actions SET status='error',error=?,updated_at=? "
        "WHERE action_id='action-1'",
        (json.dumps(error), V85_TIMESTAMP),
    )
    payload = {
        "kind": "action",
        "process_id": process_id,
        "action_id": "action-1",
        "command_id": command_id,
        "status": "error",
        "completed_at": V85_TIMESTAMP,
        "error": error,
        "failure_code": V85_FAILURE_CODE,
        "failure_stage": "resume_failed",
        "failure_message_public": "Action execution failed.",
    }
    suggestion_id = connection.execute(
        "SELECT suggestion_id FROM agent_actions WHERE action_id='action-1'"
    ).fetchone()[0]
    if suggestion_id is not None:
        payload["suggestion_id"] = suggestion_id
    connection.execute(
        "INSERT INTO process_events(process_id,event_seq,event_id,event_name,"
        "payload_json,created_at) VALUES (?,1,?,'stream_end',?,?)",
        (process_id, event_id, json.dumps(payload), V85_TIMESTAMP),
    )


def test_inventory_is_read_only_and_returns_current_envelopes_once(
    connection: sqlite3.Connection,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with connection:
        _insert_scope(connection)
        user_step = _insert_action_process(connection, "1")
        approval = _insert_action_process(
            connection, "2", continuation_kind="tool_approval"
        )
        connection.execute(
            "INSERT INTO processes(process_id,user_id,kind,status,started_at,"
            "updated_at,heartbeat_at,next_event_seq) VALUES "
            "('process-fact','user-1','fact','completed',?,?,?,1)",
            (TIMESTAMP, TIMESTAMP, TIMESTAMP),
        )
        connection.execute(
            "INSERT INTO jobs(job_id,user_id,job_type,process_id,status,scheduled_at) "
            "VALUES ('unrelated','user-1','structure_facts','process-fact','completed',?)",
            (TIMESTAMP,),
        )
        connection.execute(
            "INSERT INTO job_payloads(job_id,payload_json) VALUES ('unrelated','42')"
        )
        cutoff = connection.execute(
            "SELECT completed_at FROM migration_journal WHERE to_version=82"
        ).fetchone()[0]
        connection.execute(
            "UPDATE job_payloads SET created_at=? WHERE job_id='job-1'", (cutoff,)
        )
    decode = json.loads
    decoded_payloads = 0

    def count_decode(payload_json: str) -> object:
        nonlocal decoded_payloads
        decoded_payloads += 1
        return decode(payload_json)

    monkeypatch.setattr(json, "loads", count_decode)
    statements: list[str] = []
    connection.set_trace_callback(statements.append)
    connection.execute("PRAGMA query_only = ON")

    assert load_action_process_envelopes(connection) == (user_step, approval)
    connection.set_trace_callback(None)
    assert decoded_payloads == 3
    assert sum("FROM process_events" in statement for statement in statements) == 1
    assert sum(V85_MIGRATION_NAME in statement for statement in statements) == 1


@pytest.mark.parametrize("missing_payload", (False, True))
@pytest.mark.parametrize("with_suggestion", (False, True))
def test_inventory_uses_exact_v85_certificate_as_message_claim_fallback(
    connection: sqlite3.Connection,
    missing_payload: bool,
    with_suggestion: bool,
) -> None:
    with connection:
        _insert_scope(connection)
        expected = _insert_action_process(
            connection, "legacy", continuation_kind="tool_approval"
        )
        if with_suggestion:
            connection.execute(
                "INSERT INTO agent_suggestions(suggestion_id,user_id,status,"
                "created_at,updated_at) VALUES "
                "('suggestion-1','user-1','processing',?,?)",
                (TIMESTAMP, TIMESTAMP),
            )
            connection.execute(
                "UPDATE agent_actions SET suggestion_id='suggestion-1' "
                "WHERE action_id='action-1'"
            )
            connection.execute(
                "UPDATE processes SET suggestion_id='suggestion-1' "
                "WHERE process_id='process-legacy'"
            )
        if missing_payload:
            connection.execute("DELETE FROM job_payloads WHERE job_id='job-legacy'")
        _certify_v85_lineage(connection, "legacy")
    connection.execute("PRAGMA query_only = ON")

    assert load_action_process_envelopes(connection) == (
        expected._replace(claimed_user_message_id="message-1"),
    )


@pytest.mark.parametrize(
    "corruption",
    (
        "UPDATE jobs SET error_code='OTHER' WHERE job_id='job-legacy'",
        "UPDATE processes SET terminal_event_id=NULL WHERE process_id='process-legacy'",
        "UPDATE process_events SET event_name='other' WHERE process_id='process-legacy'",
        "UPDATE process_events SET payload_json=json_set(payload_json,'$.action_id','other') WHERE process_id='process-legacy'",
        "UPDATE process_events SET payload_json=json_set(payload_json,'$.command_id',' ') WHERE process_id='process-legacy'",
        "UPDATE process_events SET payload_json=json_remove(payload_json,'$.failure_message_public') WHERE process_id='process-legacy'",
        "UPDATE process_events SET payload_json=json_set(payload_json,'$.completed_at','other') WHERE process_id='process-legacy'",
        "UPDATE process_events SET payload_json=json_remove(payload_json,'$.error.severity') WHERE process_id='process-legacy'",
        "DELETE FROM migration_journal WHERE to_version=85",
    ),
)
def test_inventory_rejects_mismatched_or_counterfeit_v85_certificate(
    connection: sqlite3.Connection,
    corruption: str,
) -> None:
    with connection:
        _insert_scope(connection)
        _insert_action_process(connection, "legacy", continuation_kind="tool_approval")
        _certify_v85_lineage(connection, "legacy")
        connection.execute(corruption)

    _expect_error(connection, "certification|v85_event_command_id")


def test_inventory_rejects_non_emitter_v85_timestamp_grammar(
    connection: sqlite3.Connection,
) -> None:
    with connection:
        _insert_scope(connection)
        _insert_action_process(connection, "legacy", continuation_kind="tool_approval")
        _certify_v85_lineage(connection, "legacy")
        connection.execute(
            "UPDATE jobs SET completed_at=? WHERE job_id='job-legacy'",
            (COUNTERFEIT_V85_TIMESTAMP,),
        )
        connection.execute(
            "UPDATE processes SET completed_at=? WHERE process_id='process-legacy'",
            (COUNTERFEIT_V85_TIMESTAMP,),
        )
        connection.execute(
            "UPDATE process_events SET created_at=?,"
            "payload_json=json_set(payload_json,'$.completed_at',?) "
            "WHERE process_id='process-legacy'",
            (COUNTERFEIT_V85_TIMESTAMP, COUNTERFEIT_V85_TIMESTAMP),
        )

    _expect_error(connection, "invalid completed_at")


def test_inventory_uses_v85_certificate_after_action_projection_changes(
    connection: sqlite3.Connection,
) -> None:
    with connection:
        _insert_scope(connection)
        expected = _insert_action_process(
            connection, "legacy", continuation_kind="tool_approval"
        )
        _certify_v85_lineage(connection, "legacy")
        connection.execute(
            "UPDATE agent_actions SET status='queued',error=NULL,updated_at=? "
            "WHERE action_id='action-1'",
            (TIMESTAMP,),
        )
    connection.execute("PRAGMA query_only = ON")

    assert load_action_process_envelopes(connection) == (
        expected._replace(claimed_user_message_id="message-1"),
    )


def test_inventory_certifies_only_current_process_when_action_has_predecessor(
    connection: sqlite3.Connection,
) -> None:
    with connection:
        _insert_scope(connection)
        predecessor = _insert_action_process(
            connection, "predecessor", continuation_kind="tool_approval"
        )
        current = _insert_action_process(
            connection, "current", continuation_kind="tool_approval"
        )
        _certify_v85_lineage(connection, "current")
    connection.execute("PRAGMA query_only = ON")

    assert load_action_process_envelopes(connection) == (
        predecessor,
        current._replace(claimed_user_message_id="message-1"),
    )


@pytest.mark.parametrize(
    ("mutation", "pattern"),
    (
        ("DELETE FROM jobs WHERE job_id='job-1'", "process job count"),
        ("DELETE FROM job_payloads WHERE job_id='job-1'", "job payload count"),
    ),
)
def test_inventory_rejects_action_process_without_complete_job_payload(
    connection: sqlite3.Connection, mutation: str, pattern: str
) -> None:
    with connection:
        _insert_scope(connection)
        _insert_action_process(connection, "1")
        connection.execute(mutation)
    _expect_error(connection, pattern)


def test_inventory_rejects_multiple_jobs_for_one_action_process(
    connection: sqlite3.Connection,
) -> None:
    with connection:
        _insert_scope(connection)
        _insert_action_process(connection, "1")
        connection.execute(
            "INSERT INTO jobs(job_id,user_id,job_type,process_id,status,scheduled_at,"
            "logical_key) VALUES ('job-2','user-1','execute_action','process-1',"
            "'completed',?,'action-1')",
            (TIMESTAMP,),
        )
        payload = connection.execute(
            "SELECT payload_json FROM job_payloads WHERE job_id='job-1'"
        ).fetchone()[0]
        connection.execute(
            "INSERT INTO job_payloads(job_id,payload_json) VALUES ('job-2',?)",
            (payload,),
        )
    _expect_error(connection, "process job count.*count=2")


@pytest.mark.parametrize(
    "mutation",
    (
        "UPDATE jobs SET user_id='user-2' WHERE job_id='job-1'",
        "UPDATE jobs SET job_type='structure_facts' WHERE job_id='job-1'",
        "UPDATE jobs SET logical_key='action-2' WHERE job_id='job-1'",
        "UPDATE jobs SET process_id=NULL WHERE job_id='job-1'",
        "UPDATE processes SET user_id='user-2' WHERE process_id='process-1'",
        "UPDATE processes SET action_id='action-2' WHERE process_id='process-1'",
        "UPDATE processes SET kind='fact' WHERE process_id='process-1'",
        "UPDATE job_payloads SET payload_json=json_set(payload_json,'$.job_id','x')",
        "UPDATE job_payloads SET payload_json=json_set(payload_json,'$.process_id','x')",
        "UPDATE job_payloads SET payload_json=json_set(payload_json,'$.action_id','x')",
        "UPDATE job_payloads SET payload_json=json_set(payload_json,'$.user_id','x')",
    ),
)
def test_inventory_rejects_identity_or_owner_mismatch(
    connection: sqlite3.Connection, mutation: str
) -> None:
    with connection:
        _insert_scope(connection)
        _insert_action_process(connection, "1")
        connection.execute(mutation)
    _expect_error(connection, "inconsistent|count is invalid|has invalid")


@pytest.mark.parametrize("mismatch_owner", ("process", "action"))
def test_inventory_rejects_suggestion_provenance_mismatch(
    connection: sqlite3.Connection, mismatch_owner: str
) -> None:
    with connection:
        _insert_scope(connection)
        _insert_action_process(connection, "1")
        connection.execute(
            "INSERT INTO agent_suggestions(suggestion_id,user_id,status,created_at,"
            "updated_at) VALUES ('suggestion-1','user-1','processing',?,?)",
            (TIMESTAMP, TIMESTAMP),
        )
        target = "processes" if mismatch_owner == "process" else "agent_actions"
        identity = "process_id" if mismatch_owner == "process" else "action_id"
        connection.execute(
            f"UPDATE {target} SET suggestion_id='suggestion-1' WHERE {identity}=?",
            (f"{mismatch_owner}-1",),
        )
    _expect_error(connection, "process ownership is inconsistent")


@pytest.mark.parametrize(
    ("mutation", "pattern"),
    (
        (
            "UPDATE job_payloads SET payload_json=json_set(payload_json,"
            "'$.continuation_ref.kind','unsupported')",
            "Unsupported Action continuation_ref kind",
        ),
        (
            "UPDATE job_payloads SET payload_json=json_set(payload_json,"
            "'$.continuation_ref.kind','tool_approval',"
            "'$.continuation_ref.approval_session_id','approval-1',"
            "'$.continuation_ref.tool_request_id','tool-1')",
            "tool_approval continuation_ref has invalid fields",
        ),
        (
            "UPDATE job_payloads SET payload_json="
            "json_set(payload_json,'$.unexpected','value')",
            "Action job payload has invalid fields",
        ),
    ),
)
def test_inventory_rejects_invalid_current_payload_contract(
    connection: sqlite3.Connection, mutation: str, pattern: str
) -> None:
    with connection:
        _insert_scope(connection)
        _insert_action_process(connection, "1")
        connection.execute(mutation)
    _expect_error(connection, pattern)


@pytest.mark.parametrize("stored_job_id", ("unrelated", None))
def test_inventory_rejects_action_shaped_payload_without_action_job(
    connection: sqlite3.Connection, stored_job_id: str | None
) -> None:
    with connection:
        _insert_scope(connection)
        _insert_action_process(connection, "1")
        payload = connection.execute(
            "SELECT payload_json FROM job_payloads WHERE job_id='job-1'"
        ).fetchone()[0]
        if stored_job_id is not None:
            connection.execute(
                "INSERT INTO jobs(job_id,user_id,job_type,status,scheduled_at) "
                "VALUES ('unrelated','user-1','structure_facts','completed',?)",
                (TIMESTAMP,),
            )
        connection.execute(
            "INSERT INTO job_payloads(job_id,payload_json) VALUES (?,?)",
            (stored_job_id, payload),
        )
    _expect_error(connection, "process envelope is inconsistent")


@pytest.mark.parametrize(
    ("payload_created_at", "action_status", "runtime_status", "pattern"),
    (
        ("2000-01-01T00:00:00Z", "processing", "completed", None),
        ("2000-01-01T00:00:00Z", "queued", "completed", None),
        ("2000-01-01T00:00:00Z", "processing", "running", "missing continuation_ref"),
        ("v82-cutoff", "processing", "completed", "missing continuation_ref"),
        ("!", "processing", "completed", "invalid payload_created_at"),
        ("invalid-cutoff", "processing", "completed", "invalid v82_completed_at"),
        (NAIVE_TIMESTAMP, "processing", "completed", "invalid payload_created_at"),
        (INVALID_TIMESTAMP, "processing", "completed", "invalid payload_created_at"),
    ),
)
def test_inventory_classifies_only_strict_pre_v82_terminal_legacy_payload(
    connection: sqlite3.Connection,
    payload_created_at: str,
    action_status: str,
    runtime_status: str,
    pattern: str | None,
) -> None:
    with connection:
        _insert_scope(connection)
        _insert_action_process(connection, "legacy")
        connection.execute("UPDATE agent_actions SET status=?", (action_status,))
        connection.execute("UPDATE jobs SET status=?", (runtime_status,))
        connection.execute("UPDATE processes SET status=?", (runtime_status,))
        if payload_created_at == "invalid-cutoff":
            connection.execute(
                "UPDATE migration_journal SET completed_at='!' WHERE to_version=82"
            )
            payload_created_at = "2000-01-01T00:00:00Z"
        if payload_created_at == "v82-cutoff":
            payload_created_at = connection.execute(
                "SELECT completed_at FROM migration_journal WHERE to_version=82"
            ).fetchone()[0]
        connection.execute(
            "UPDATE job_payloads SET payload_json=?,created_at=? "
            "WHERE job_id='job-legacy'",
            (json.dumps({"legacy": "payload"}), payload_created_at),
        )
    if pattern is None:
        connection.execute("PRAGMA query_only = ON")
        assert load_action_process_envelopes(connection) == ()
    else:
        _expect_error(connection, pattern)


@pytest.mark.parametrize("invalid_payload", ('{"private":"value"', b'{"private":1}'))
@pytest.mark.parametrize("is_action", (False, True))
def test_inventory_classifies_malformed_or_non_text_payload(
    connection: sqlite3.Connection, invalid_payload: str | bytes, is_action: bool
) -> None:
    with connection:
        _insert_scope(connection)
        if is_action:
            _insert_action_process(connection, "1")
        else:
            connection.execute(
                "INSERT INTO jobs(job_id,user_id,job_type,status,scheduled_at) "
                "VALUES ('unrelated','user-1','structure_facts','completed',?)",
                (TIMESTAMP,),
            )
        job_id = "job-1" if is_action else "unrelated"
        connection.execute("PRAGMA ignore_check_constraints = ON")
        connection.execute(
            "INSERT OR REPLACE INTO job_payloads(job_id,payload_json) VALUES (?,?)",
            (job_id, invalid_payload),
        )
        connection.execute("PRAGMA ignore_check_constraints = OFF")
    connection.execute("PRAGMA query_only = ON")
    if not is_action:
        assert load_action_process_envelopes(connection) == ()
        return
    with pytest.raises(MigrationError, match="malformed job payload JSON"):
        load_action_process_envelopes(connection)
