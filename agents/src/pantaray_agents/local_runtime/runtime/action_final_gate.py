"""Read-only finalization gate predicates for a parent Action.

A parent may only answer normally once nothing it owns can still change the
Action: no child can run, every terminal child result has been collected, no
approval is waiting for a human decision, and no resource claim is held. The
durable barrier for those invariants lives in the parent terminal transaction;
this module reads the same facts before the parent commits to an answer so the
supervisor is told which child, approval, or claim is still open instead of
failing opaquely at its terminal.

Every predicate here reads. Settling the reported work is the caller's job, and
the child settlement barrier remains the final authority.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from ..storage.migrations import MigrationError
from ..storage.migrations.connection import configure_connection
from .action_subagent_parent_lifecycle import (
    read_active_child_claim_ids,
    read_nonterminal_child_process_ids,
)
from .job_types import (
    ACTION_PROCESS_KIND,
    ACTION_SUBAGENT_PROCESS_KIND,
    LOCAL_ACTION_JOB_TYPE,
)

_PARENT_AUTHORITY_SQL = """
SELECT 1
FROM agent_actions AS action
JOIN processes AS parent
  ON parent.action_id = action.action_id AND parent.user_id = action.user_id
JOIN jobs AS job
  ON job.job_id = parent.current_job_id
 AND job.process_id = parent.process_id
 AND job.user_id = parent.user_id
WHERE action.action_id = :action_id
  AND action.user_id = :user_id
  AND action.status = 'processing'
  AND parent.process_id = :parent_process_id
  AND parent.kind = :parent_kind
  AND parent.status = 'running'
  AND parent.current_job_id = :parent_job_id
  AND job.job_type = :action_job_type
  AND job.status = 'running'
  AND job.logical_key = :action_id
  AND job.cancel_requested_at IS NULL
"""

_UNCOLLECTED_CHILDREN_SQL = """
SELECT process_id FROM processes
WHERE user_id = ? AND action_id = ? AND parent_process_id = ? AND kind = ?
  AND status IN ('completed', 'failed', 'canceled')
  AND result_collected_at IS NULL
ORDER BY process_id
"""

_PENDING_APPROVAL_SESSIONS_SQL = """
SELECT approval_session_id FROM approval_sessions
WHERE user_id = ? AND action_id = ? AND status = 'pending'
ORDER BY approval_session_id
"""


class ActionFinalizationAuthorityError(RuntimeError):
    """The parent no longer owns a finalizable, unfenced Action run."""


@dataclass(frozen=True, slots=True)
class ActionFinalizationRequest:
    user_id: str
    action_id: str
    parent_process_id: str
    parent_job_id: str


@dataclass(frozen=True, slots=True)
class ActionFinalizationBlockers:
    """Everything the parent still owns that forbids a normal final answer."""

    live_child_process_ids: tuple[str, ...]
    uncollected_child_process_ids: tuple[str, ...]
    pending_approval_session_ids: tuple[str, ...]
    active_claim_ids: tuple[str, ...]

    @property
    def blocked(self) -> bool:
        return bool(
            self.live_child_process_ids
            or self.uncollected_child_process_ids
            or self.pending_approval_session_ids
            or self.active_claim_ids
        )


def read_action_finalization_blockers(
    *,
    db_path: Path,
    busy_timeout_ms: int,
    request: ActionFinalizationRequest,
) -> ActionFinalizationBlockers:
    if busy_timeout_ms <= 0:
        raise MigrationError("LOCAL_DB_BUSY_TIMEOUT_MS must be a positive integer")
    with sqlite3.connect(db_path) as connection:
        configure_connection(connection, busy_timeout_ms)
        return read_action_finalization_blockers_in_connection(
            connection, request=request
        )


def read_action_finalization_blockers_in_connection(
    connection: sqlite3.Connection,
    *,
    request: ActionFinalizationRequest,
) -> ActionFinalizationBlockers:
    """Read the gate facts for one parent run in a single connection.

    Raises when the parent no longer owns the run or its job carries a Stop
    fence: such a parent must converge on the canceled winner its terminal owner
    already decided, not negotiate a normal answer.
    """

    _require_finalizable_parent(connection, request)
    return ActionFinalizationBlockers(
        live_child_process_ids=read_nonterminal_child_process_ids(
            connection,
            user_id=request.user_id,
            action_id=request.action_id,
            parent_process_id=request.parent_process_id,
        ),
        uncollected_child_process_ids=_uncollected_child_process_ids(
            connection, request
        ),
        pending_approval_session_ids=_pending_approval_session_ids(connection, request),
        active_claim_ids=read_active_child_claim_ids(
            connection,
            user_id=request.user_id,
            action_id=request.action_id,
            parent_process_id=request.parent_process_id,
        ),
    )


def _require_finalizable_parent(
    connection: sqlite3.Connection,
    request: ActionFinalizationRequest,
) -> None:
    row = connection.execute(
        _PARENT_AUTHORITY_SQL,
        {
            "action_id": request.action_id,
            "action_job_type": LOCAL_ACTION_JOB_TYPE,
            "parent_job_id": request.parent_job_id,
            "parent_kind": ACTION_PROCESS_KIND,
            "parent_process_id": request.parent_process_id,
            "user_id": request.user_id,
        },
    ).fetchone()
    if row is None:
        raise ActionFinalizationAuthorityError(
            "Action finalization parent authority is not active"
        )


def _uncollected_child_process_ids(
    connection: sqlite3.Connection,
    request: ActionFinalizationRequest,
) -> tuple[str, ...]:
    rows = connection.execute(
        _UNCOLLECTED_CHILDREN_SQL,
        (
            request.user_id,
            request.action_id,
            request.parent_process_id,
            ACTION_SUBAGENT_PROCESS_KIND,
        ),
    ).fetchall()
    return tuple(str(row[0]) for row in rows)


def _pending_approval_session_ids(
    connection: sqlite3.Connection,
    request: ActionFinalizationRequest,
) -> tuple[str, ...]:
    rows = connection.execute(
        _PENDING_APPROVAL_SESSIONS_SQL,
        (request.user_id, request.action_id),
    ).fetchall()
    return tuple(str(row[0]) for row in rows)
