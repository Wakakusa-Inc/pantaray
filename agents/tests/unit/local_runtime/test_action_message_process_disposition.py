from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from pantaray_agents.local_runtime.runtime import (
    action_message_process_disposition as disposition,
)
from pantaray_agents.local_runtime.runtime.action_logical_run_authority import (
    ActionLogicalRunSelection,
    select_action_logical_run_authorities_in_connection,
)
from pantaray_agents.local_runtime.runtime.action_message_process_disposition import (
    classify_action_process_disposition_in_connection,
)
from pantaray_agents.local_runtime.storage.migrations import MigrationError

_NONSELECTED_ACTION_RUN_COUNT = 10_000
_MAX_SELECTED_AUTHORITY_VM_STEPS = 1_000


@pytest.fixture
def disposition_db(tmp_path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(tmp_path / "runtime.db")
    connection.row_factory = sqlite3.Row
    connection.executescript(
        """
        CREATE TABLE processes (process_id TEXT PRIMARY KEY, user_id TEXT NOT NULL,
            kind TEXT NOT NULL, status TEXT NOT NULL, action_id TEXT,
            started_at TEXT NOT NULL, completed_at TEXT, terminal_event_id TEXT);
        CREATE TABLE jobs (job_id TEXT PRIMARY KEY, user_id TEXT NOT NULL,
            job_type TEXT NOT NULL, process_id TEXT, status TEXT NOT NULL,
            logical_key TEXT, completed_at TEXT);
        CREATE TABLE process_events (process_id TEXT NOT NULL, event_id TEXT NOT NULL,
            event_name TEXT NOT NULL, payload_json TEXT NOT NULL, created_at TEXT NOT NULL);
        CREATE TABLE job_payloads (job_id TEXT PRIMARY KEY, payload_json TEXT NOT NULL);
        CREATE TABLE agent_action_steps (step_id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL, action_id TEXT NOT NULL,
            step_type TEXT NOT NULL, status TEXT NOT NULL, accepted_sequence INTEGER,
            adopted_process_id TEXT);
        CREATE INDEX idx_jobs_process_id ON jobs(process_id);
        CREATE INDEX idx_jobs_type_logical_key ON jobs(job_type, logical_key);
        CREATE UNIQUE INDEX idx_process_events_identity
            ON process_events(process_id, event_id);
        CREATE INDEX idx_agent_action_steps_adopted_process
            ON agent_action_steps(user_id, action_id, adopted_process_id);
        """
    )
    yield connection
    connection.close()


def _insert_segment(
    connection: sqlite3.Connection,
    *,
    process_id: str,
    process_status: str,
    job_status: str,
    accepted_sequence: int | None = None,
    user_id: str = "user-1",
    action_id: str = "action-1",
) -> None:
    completed_at = (
        "2026-08-29T00:00:00.000Z"
        if process_status in {"completed", "failed", "canceled"}
        else None
    )
    terminal_event_id = None if completed_at is None else f"event-{process_id}"
    connection.execute(
        "INSERT INTO processes VALUES "
        "(?, ?, 'action', ?, ?, '2026-08-29T00:00:00.000Z', ?, ?)",
        (
            process_id,
            user_id,
            process_status,
            action_id,
            completed_at,
            terminal_event_id,
        ),
    )
    connection.execute(
        "INSERT INTO jobs VALUES (?, ?, 'execute_action', ?, ?, ?, ?)",
        (f"job-{process_id}", user_id, process_id, job_status, action_id, completed_at),
    )
    connection.execute(
        "INSERT INTO job_payloads VALUES (?, ?)",
        (
            f"job-{process_id}",
            json.dumps(
                {
                    "job_id": f"job-{process_id}",
                    "process_id": process_id,
                    "action_id": action_id,
                    "user_id": user_id,
                    "continuation_ref": {
                        "kind": "user_step",
                        "user_step_id": f"step-{process_id}",
                    },
                }
            ),
        ),
    )
    if terminal_event_id is not None:
        connection.execute(
            "INSERT INTO process_events VALUES (?, ?, 'stream_end', '{}', ?)",
            (process_id, terminal_event_id, completed_at),
        )
    if accepted_sequence is not None:
        connection.execute(
            "INSERT INTO agent_action_steps VALUES (?, ?, ?, 'user_request', "
            "'success', ?, ?)",
            (f"step-{process_id}", user_id, action_id, accepted_sequence, process_id),
        )


def _classify(
    connection: sqlite3.Connection, expected_process_id: str | None
) -> disposition.ActionProcessDispositionResult:
    return classify_action_process_disposition_in_connection(
        connection=connection,
        user_id="user-1",
        action_id="action-1",
        expected_process_id=expected_process_id,
    )


@pytest.mark.parametrize(
    ("process_status", "job_status", "expected", "required_action_status"),
    [
        ("enqueued", "queued", "active", None),
        ("running", "running", "active", None),
        ("paused", "paused", "approval_paused", None),
        ("completed", "completed", "normal_terminal", "success"),
        ("failed", "failed", "normal_terminal", "error"),
        ("canceled", "canceled", "canceled", "canceled"),
    ],
)
def test_classifies_each_canonical_status_pair(
    disposition_db: sqlite3.Connection,
    process_status: str,
    job_status: str,
    expected: disposition.ActionProcessDisposition,
    required_action_status: disposition.ActionTerminalStatus | None,
) -> None:
    _insert_segment(
        disposition_db,
        process_id="root-1",
        process_status=process_status,
        job_status=job_status,
        accepted_sequence=1,
    )

    result = _classify(disposition_db, "root-1")
    assert result == disposition.ActionProcessDispositionResult(
        expected, required_action_status
    )


def test_null_fence_is_idle_only_without_an_active_run(
    disposition_db: sqlite3.Connection,
) -> None:
    assert _classify(disposition_db, None).disposition == "idle"
    with pytest.raises(MigrationError, match="caller-owned transaction"):
        select_action_logical_run_authorities_in_connection(
            connection=disposition_db,
            user_id="user-1",
            selections=frozenset({ActionLogicalRunSelection("action-1", "missing")}),
        )
    disposition_db.execute("BEGIN")
    assert (
        select_action_logical_run_authorities_in_connection(
            connection=disposition_db,
            user_id="user-1",
            selections=frozenset(),
        )
        == ()
    )
    with pytest.raises(MigrationError, match="envelope is not singular"):
        select_action_logical_run_authorities_in_connection(
            connection=disposition_db,
            user_id="user-1",
            selections=frozenset({ActionLogicalRunSelection("action-1", "missing")}),
        )
    _insert_segment(
        disposition_db,
        process_id="root-1",
        process_status="running",
        job_status="running",
        accepted_sequence=1,
    )

    assert _classify(disposition_db, None).disposition == "stale"
    disposition_db.execute(
        "UPDATE processes SET status='completed' WHERE process_id='root-1'"
    )
    disposition_db.execute(
        "UPDATE jobs SET status='completed' WHERE process_id='root-1'"
    )
    assert _classify(disposition_db, None).disposition == "idle"


def test_selects_exact_terminal_authority_for_one_logical_run(
    disposition_db: sqlite3.Connection,
) -> None:
    _insert_segment(
        disposition_db,
        process_id="root-0",
        process_status="completed",
        job_status="completed",
        accepted_sequence=1,
    )
    _insert_segment(
        disposition_db,
        process_id="root-1",
        process_status="failed",
        job_status="failed",
        accepted_sequence=2,
    )
    disposition_db.execute(
        "INSERT INTO agent_action_steps VALUES "
        "('steer-root-1', 'user-1', 'action-1', 'user_request', 'success', 3, "
        "'root-1')"
    )
    disposition_db.execute(
        "UPDATE process_events SET payload_json = ? WHERE process_id = 'root-0'",
        ("x" * 1_000_000,),
    )

    def reject_nonselected_payload_read(
        cursor: sqlite3.Cursor, values: tuple[object, ...]
    ) -> sqlite3.Row:
        row = sqlite3.Row(cursor, values)
        payload_columns = {
            "payload_json",
            "terminal_event_payload_json",
        } & set(row.keys())
        if row["process_id"] == "root-0" and payload_columns:
            raise AssertionError("nonselected terminal payload was read")
        return row

    disposition_db.row_factory = reject_nonselected_payload_read

    authorities = select_action_logical_run_authorities_in_connection(
        connection=disposition_db,
        user_id="user-1",
        selections=frozenset({ActionLogicalRunSelection("action-1", "root-1")}),
    )

    assert len(authorities) == 1
    authority = authorities[0]
    assert authority.action_id == "action-1"
    assert authority.root_process_id == "root-1"
    assert authority.root_accepted_sequence == 2
    assert authority.process_status == "failed"
    assert authority.job_id == "job-root-1"
    assert authority.terminal_event_id == "event-root-1"
    assert authority.terminal_event_payload_json == "{}"

    disposition_db.execute(
        "UPDATE jobs SET completed_at = '2099-01-01T00:00:00.000Z' "
        "WHERE process_id = 'root-1'"
    )
    with pytest.raises(MigrationError, match="terminal timestamps"):
        select_action_logical_run_authorities_in_connection(
            connection=disposition_db,
            user_id="user-1",
            selections=frozenset({ActionLogicalRunSelection("action-1", "root-1")}),
        )
    disposition_db.execute(
        "UPDATE jobs SET completed_at = '2026-08-29T00:00:00.000Z' "
        "WHERE process_id = 'root-1'"
    )
    disposition_db.execute("DELETE FROM process_events WHERE process_id = 'root-1'")
    with pytest.raises(MigrationError, match="terminal event is missing"):
        select_action_logical_run_authorities_in_connection(
            connection=disposition_db,
            user_id="user-1",
            selections=frozenset({ActionLogicalRunSelection("action-1", "root-1")}),
        )


def test_selects_active_and_terminal_runs_across_actions_in_two_queries(
    disposition_db: sqlite3.Connection,
) -> None:
    _insert_segment(
        disposition_db,
        action_id="action-1",
        process_id="active-1",
        process_status="running",
        job_status="running",
        accepted_sequence=1,
    )
    _insert_segment(
        disposition_db,
        action_id="action-2",
        process_id="terminal-2",
        process_status="completed",
        job_status="completed",
        accepted_sequence=1,
    )
    selects: list[str] = []
    disposition_db.set_trace_callback(
        lambda statement: (
            selects.append(statement)
            if statement.lstrip().upper().startswith(("SELECT", "WITH"))
            else None
        )
    )

    authorities = select_action_logical_run_authorities_in_connection(
        connection=disposition_db,
        user_id="user-1",
        selections=frozenset(
            {
                ActionLogicalRunSelection("action-1", "active-1"),
                ActionLogicalRunSelection("action-2", "terminal-2"),
            }
        ),
    )
    mixed_select_count = len(selects)
    selects.clear()
    active_authorities = select_action_logical_run_authorities_in_connection(
        connection=disposition_db,
        user_id="user-1",
        selections=frozenset({ActionLogicalRunSelection("action-1", "active-1")}),
    )
    disposition_db.set_trace_callback(None)
    assert [
        (
            authority.action_id,
            authority.root_accepted_sequence,
            authority.process_status,
        )
        for authority in authorities
    ] == [
        ("action-1", 1, "running"),
        ("action-2", 1, "completed"),
    ]
    assert mixed_select_count == 2
    assert [item.action_id for item in active_authorities] == ["action-1"]
    assert len(selects) == 1


@pytest.mark.parametrize(
    ("corruption", "expected_error"),
    [
        ("selected_action", "envelope is not singular"),
        ("additional_job", "envelope is not singular"),
        ("payload_action", "job payload identity is inconsistent"),
        ("payload_process", "job payload identity is inconsistent"),
    ],
)
def test_rejects_cross_action_process_and_payload_mismatches(
    disposition_db: sqlite3.Connection,
    corruption: str,
    expected_error: str,
) -> None:
    _insert_segment(
        disposition_db,
        process_id="root-1",
        process_status="running",
        job_status="running",
        accepted_sequence=1,
    )
    selection = ActionLogicalRunSelection("action-1", "root-1")
    if corruption == "selected_action":
        selection = ActionLogicalRunSelection("action-2", "root-1")
    elif corruption == "additional_job":
        disposition_db.execute(
            "INSERT INTO jobs VALUES "
            "('job-extra', 'user-1', 'other', 'root-1', 'running', "
            "'action-2', NULL)"
        )
    else:
        payload = json.loads(
            disposition_db.execute(
                "SELECT payload_json FROM job_payloads WHERE job_id='job-root-1'"
            ).fetchone()[0]
        )
        field = "process_id" if corruption == "payload_process" else "action_id"
        payload[field] = "other"
        disposition_db.execute(
            "UPDATE job_payloads SET payload_json=? WHERE job_id='job-root-1'",
            (json.dumps(payload),),
        )

    with pytest.raises(MigrationError, match=expected_error):
        select_action_logical_run_authorities_in_connection(
            connection=disposition_db,
            user_id="user-1",
            selections=frozenset({selection}),
        )


def test_selected_authority_cost_ignores_nonselected_action_inventory(
    disposition_db: sqlite3.Connection,
) -> None:
    _insert_segment(
        disposition_db,
        process_id="selected",
        process_status="completed",
        job_status="completed",
        accepted_sequence=1,
    )
    for index in range(_NONSELECTED_ACTION_RUN_COUNT):
        _insert_segment(
            disposition_db,
            action_id="action-2",
            process_id=f"other-{index}",
            process_status="completed",
            job_status="completed",
            accepted_sequence=index + 2,
        )
    disposition_db.execute(
        "UPDATE job_payloads SET payload_json = 'not-json' "
        "WHERE job_id != 'job-selected'"
    )
    selects: list[str] = []
    vm_steps = 0

    def count_vm_step() -> int:
        nonlocal vm_steps
        vm_steps += 1
        return 0

    disposition_db.set_trace_callback(
        lambda statement: (
            selects.append(statement)
            if statement.lstrip().upper().startswith(("SELECT", "WITH"))
            else None
        )
    )
    disposition_db.set_progress_handler(count_vm_step, 1)

    authorities = select_action_logical_run_authorities_in_connection(
        connection=disposition_db,
        user_id="user-1",
        selections=frozenset({ActionLogicalRunSelection("action-1", "selected")}),
    )

    disposition_db.set_trace_callback(None)
    disposition_db.set_progress_handler(None, 0)
    assert [authority.root_process_id for authority in authorities] == ["selected"]
    assert len(selects) == 2
    # A user-wide adopted-step materialization exceeds 100k VM steps here.
    assert vm_steps < _MAX_SELECTED_AUTHORITY_VM_STEPS


def test_rejects_one_representative_noncanonical_status_pair(
    disposition_db: sqlite3.Connection,
) -> None:
    _insert_segment(
        disposition_db,
        process_id="root-1",
        process_status="running",
        job_status="queued",
        accepted_sequence=1,
    )

    with pytest.raises(MigrationError, match="status pair is noncanonical"):
        _classify(disposition_db, "root-1")


def test_rejects_independent_inventory_mismatch(
    disposition_db: sqlite3.Connection,
) -> None:
    disposition_db.execute(
        "INSERT INTO jobs VALUES "
        "('orphan-job', 'user-1', 'execute_action', 'orphan', 'queued', "
        "'action-1', NULL)"
    )

    with pytest.raises(MigrationError, match="inventories are inconsistent"):
        _classify(disposition_db, None)


@pytest.mark.parametrize(
    ("older_sequence", "older_active", "message"),
    [
        (3, False, "share a root accepted_sequence"),
        (2, True, "Only the latest Action logical run may be active"),
    ],
)
def test_rejects_ambiguous_logical_run_structure(
    disposition_db: sqlite3.Connection,
    older_sequence: int,
    older_active: bool,
    message: str,
) -> None:
    _insert_segment(
        disposition_db,
        process_id="root-1",
        process_status="running" if older_active else "completed",
        job_status="running" if older_active else "completed",
        accepted_sequence=older_sequence,
    )
    _insert_segment(
        disposition_db,
        process_id="root-2",
        process_status="completed",
        job_status="completed",
        accepted_sequence=3,
    )

    with pytest.raises(MigrationError, match=message):
        _classify(disposition_db, "root-2")
