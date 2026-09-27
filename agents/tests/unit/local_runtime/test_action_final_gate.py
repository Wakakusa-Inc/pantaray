from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from pantaray_agents.local_runtime.runtime.action_final_gate import (
    ActionFinalizationAuthorityError,
    ActionFinalizationBlockers,
    ActionFinalizationRequest,
    read_action_finalization_blockers,
)
from pantaray_agents.local_runtime.runtime.action_subagent_terminal import (
    build_action_subagent_failure_result,
    finalize_action_subagent_terminal,
)
from pantaray_agents.local_runtime.runtime.action_subagent_wait import (
    collect_action_subagent_results_in_connection,
)
from pantaray_agents.local_runtime.storage.transactions import immediate_transaction
from pantaray_agents.schema.agent.action_subagent import (
    ActionSubagentCollectionReceipt,
    ActionSubagentWaitRequest,
)

from .test_action_parent_child_settlement import (
    PARENT_JOB_ID,
    PARENT_PROCESS_ID,
    SEEDED_AT,
    _claim_child,
    _fence_parent,
    _parent_runtime,
    _pause_child,
    _seed_child,
)
from .test_action_terminal_repository import BUSY_TIMEOUT_MS

COLLECTED_AT = "2026-03-24T00:05:00Z"
NOTHING_BLOCKS = ActionFinalizationBlockers((), (), (), ())
REQUEST = ActionFinalizationRequest(
    user_id="user-1",
    action_id="action-1",
    parent_process_id=PARENT_PROCESS_ID,
    parent_job_id=PARENT_JOB_ID,
)


def _blockers(db_path: Path) -> ActionFinalizationBlockers:
    return read_action_finalization_blockers(
        db_path=db_path,
        busy_timeout_ms=BUSY_TIMEOUT_MS,
        request=REQUEST,
    )


def _collect(db_path: Path, child_process_id: str) -> None:
    with sqlite3.connect(db_path) as connection:
        connection.row_factory = sqlite3.Row
        with immediate_transaction(connection):
            collect_action_subagent_results_in_connection(
                connection,
                receipt=ActionSubagentCollectionReceipt(
                    request=ActionSubagentWaitRequest(
                        user_id="user-1",
                        action_id="action-1",
                        parent_process_id=PARENT_PROCESS_ID,
                        parent_job_id=PARENT_JOB_ID,
                        child_process_ids=(child_process_id,),
                    ),
                    collected_at=COLLECTED_AT,
                ),
            )


def _child_status(db_path: Path, child_process_id: str) -> str:
    with sqlite3.connect(db_path) as connection:
        return str(
            connection.execute(
                "SELECT status FROM processes WHERE process_id = ?",
                (child_process_id,),
            ).fetchone()[0]
        )


def _insert_pending_approval(
    db_path: Path, *, session_id: str, action_id: str = "action-1"
) -> None:
    with sqlite3.connect(db_path) as connection, connection:
        connection.execute(
            "INSERT INTO approval_sessions(approval_session_id,user_id,action_id,"
            "tool_request_id,tool_id,intent_class,approval_source,status,"
            "approved_capabilities_json,command_summary_json,requested_at,created_at)"
            " VALUES (?,'user-1',?,?,'apply_patch','write','prompt','pending',"
            "'{}',?,?,?)",
            (
                session_id,
                action_id,
                f"request-{session_id}",
                json.dumps({}),
                SEEDED_AT,
                SEEDED_AT,
            ),
        )


def _seed_second_action(db_path: Path) -> None:
    with sqlite3.connect(db_path) as connection, connection:
        connection.execute(
            """
            INSERT INTO agent_actions(
                action_id, user_id, suggestion_id, initial_user_message_id,
                execution_target_json, status, final_output, prompt_name,
                prompt_version, created_at, updated_at
            ) VALUES ('action-2', 'user-1', NULL, 'command-2',
                      '{"kind":"scratch"}', 'processing', '', 'action/executing',
                      '1.0', ?, ?)
            """,
            (SEEDED_AT, SEEDED_AT),
        )


def test_a_parent_owning_no_open_work_is_not_blocked(tmp_path: Path) -> None:
    db_path = _parent_runtime(tmp_path)

    blockers = _blockers(db_path)

    assert blockers == NOTHING_BLOCKS
    assert blockers.blocked is False


def test_a_child_blocks_finalization_in_every_nonterminal_state(
    tmp_path: Path,
) -> None:
    db_path = _parent_runtime(tmp_path)
    child = _seed_child(db_path)
    child_process_id = child["process_id"]

    assert _child_status(db_path, child_process_id) == "enqueued"
    assert _blockers(db_path).live_child_process_ids == (child_process_id,)

    _claim_child(db_path)

    assert _child_status(db_path, child_process_id) == "running"
    assert _blockers(db_path).live_child_process_ids == (child_process_id,)

    session_id = _pause_child(db_path, child)

    # An approval-paused child is reported by both predicates: the approval is
    # what a human must decide, the process is what can still run afterwards.
    assert _child_status(db_path, child_process_id) == "paused"
    paused = _blockers(db_path)
    assert paused.live_child_process_ids == (child_process_id,)
    assert paused.pending_approval_session_ids == (session_id,)


def test_a_terminal_child_blocks_finalization_until_its_result_is_collected(
    tmp_path: Path,
) -> None:
    """A failed child is collectible work, not a blocker of its own.

    The parent decides semantically whether to retry, replace, disclose, or
    finish after the child lifecycle settles, so the gate asks only that the
    result was collected.
    """

    db_path = _parent_runtime(tmp_path)
    child = _seed_child(db_path)
    _claim_child(db_path)
    finalize_action_subagent_terminal(
        db_path=db_path,
        busy_timeout_ms=BUSY_TIMEOUT_MS,
        payload=child,
        result=build_action_subagent_failure_result("child_tool_failed"),
    )

    uncollected = _blockers(db_path)
    assert uncollected.uncollected_child_process_ids == (child["process_id"],)
    assert uncollected.live_child_process_ids == ()
    assert uncollected.active_claim_ids == ()

    _collect(db_path, child["process_id"])

    assert _blockers(db_path) == NOTHING_BLOCKS


def test_a_claim_outliving_its_child_blocks_finalization(tmp_path: Path) -> None:
    """Today's external Stop cancels a child process without its claims.

    Such a claim is unreachable state rather than pending work, so the gate must
    report it instead of letting the parent answer over a held resource.
    """

    db_path = _parent_runtime(tmp_path)
    child = _seed_child(db_path)
    with sqlite3.connect(db_path) as connection, connection:
        connection.execute(
            "UPDATE processes SET status = 'canceled', result_collected_at = ?"
            " WHERE process_id = ?",
            (COLLECTED_AT, child["process_id"]),
        )

    blockers = _blockers(db_path)

    assert blockers.active_claim_ids == ("claim-1",)
    assert blockers.live_child_process_ids == ()
    assert blockers.uncollected_child_process_ids == ()


def test_only_a_pending_approval_of_this_action_blocks_finalization(
    tmp_path: Path,
) -> None:
    db_path = _parent_runtime(tmp_path)
    _insert_pending_approval(db_path, session_id="session-root")
    _seed_second_action(db_path)
    _insert_pending_approval(db_path, session_id="session-other", action_id="action-2")

    assert _blockers(db_path).pending_approval_session_ids == ("session-root",)

    with sqlite3.connect(db_path) as connection, connection:
        connection.execute(
            "UPDATE approval_sessions SET status = 'interrupted', decided_at = ?"
            " WHERE approval_session_id = 'session-root'",
            (COLLECTED_AT,),
        )

    assert _blockers(db_path) == NOTHING_BLOCKS


def test_a_stop_fenced_parent_cannot_read_a_finalization_verdict(
    tmp_path: Path,
) -> None:
    db_path = _parent_runtime(tmp_path)
    _fence_parent(db_path)

    with pytest.raises(ActionFinalizationAuthorityError):
        _blockers(db_path)
