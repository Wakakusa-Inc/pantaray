"""Parent-side child settlement at the Action terminal boundary.

A parent Action must not become terminal while one of its subagent children or
one of their resource claims can still mutate the workspace. This module owns
that barrier for the worker terminal transaction. It applies the canonical
single-child cancel core to every child the parent still owns: queued and
approval-paused children settle as canceled immediately, while a running child
only records the durable cancel request and keeps its claims until its own
worker reaches a safe boundary. The caller therefore commits those requests and
retries its terminal instead of terminalizing the parent over a live child.
Because a child releases its claims in the transaction that settles it, a claim
that outlives every child is unreachable state rather than pending work, and the
barrier reports it as an integrity failure instead of waiting for it.

The same transaction also lets a durable parent Stop fence win over a late
worker success or error, mirroring the child terminal owner.
"""

from __future__ import annotations

import sqlite3
from dataclasses import replace

from pantaray_agents.action_status import (
    ACTION_FAILURE_CODE_CANCELED,
    ACTION_FAILURE_MESSAGE_CANCELED,
    ACTION_FAILURE_STAGE_RUNNING_FAILED,
    ACTION_STATUS_CANCELED,
    FinalizeActionTerminalCommand,
)

from ..storage.transactions import SQLiteTransactionOwnershipError
from .action_subagent_cancel import (
    ActionSubagentCancelRequest,
    request_action_subagent_cancellation_in_connection,
)
from .job_envelope import LocalJobEnvelopeIntegrityError
from .job_types import ACTION_SUBAGENT_PROCESS_KIND, LOCAL_ACTION_JOB_TYPE

_NONTERMINAL_CHILDREN_SQL = """
SELECT process_id FROM processes
WHERE user_id = ? AND action_id = ? AND parent_process_id = ? AND kind = ?
  AND status IN ('enqueued', 'running', 'paused')
ORDER BY process_id
"""

_ACTIVE_CLAIM_IDS_SQL = """
SELECT claim_id FROM action_subagent_resource_claims
WHERE user_id = ? AND action_id = ? AND parent_process_id = ?
  AND released_at IS NULL
ORDER BY claim_id
"""


class ActionChildSettlementPendingError(RuntimeError):
    """A child of the terminalizing parent can still mutate the Action."""


def settle_action_subagent_children_in_connection(
    *,
    connection: sqlite3.Connection,
    command: FinalizeActionTerminalCommand,
    job_id: str,
) -> bool:
    """Cancel every child the parent still owns and report the barrier.

    ``False`` means a running child survived this transaction, so the caller
    must commit the recorded cancel requests without writing the parent
    terminal. A claim that outlived every child cannot be settled by any later
    transaction, so it fails loudly instead of holding the caller forever.
    """

    if not connection.in_transaction:
        raise SQLiteTransactionOwnershipError(
            "Action child settlement requires a caller-owned transaction"
        )
    for child_process_id in _live_children(connection, command):
        request_action_subagent_cancellation_in_connection(
            connection=connection,
            request=ActionSubagentCancelRequest(
                user_id=command.user_id,
                action_id=command.action_id,
                parent_process_id=command.process_id,
                parent_job_id=job_id,
                child_process_id=child_process_id,
            ),
        )
    if _live_children(connection, command):
        return False
    active_claims = read_active_child_claim_ids(
        connection,
        user_id=command.user_id,
        action_id=command.action_id,
        parent_process_id=command.process_id,
    )
    if active_claims:
        raise LocalJobEnvelopeIntegrityError(
            f"Action {command.action_id} holds {len(active_claims)} subagent "
            "claim(s) without a nonterminal child"
        )
    return True


def resolve_action_terminal_cancel_winner_in_connection(
    *,
    connection: sqlite3.Connection,
    command: FinalizeActionTerminalCommand,
    job_id: str,
) -> FinalizeActionTerminalCommand:
    """Read a late worker success or error back as the fenced cancel winner."""

    if command.action_status == ACTION_STATUS_CANCELED:
        return command
    fenced = connection.execute(
        """
        SELECT 1 FROM jobs
        WHERE job_id = ? AND user_id = ? AND job_type = ? AND logical_key = ?
          AND cancel_requested_at IS NOT NULL
        """,
        (job_id, command.user_id, LOCAL_ACTION_JOB_TYPE, command.action_id),
    ).fetchone()
    if fenced is None:
        return command
    return replace(
        command,
        action_status=ACTION_STATUS_CANCELED,
        failure_code=ACTION_FAILURE_CODE_CANCELED,
        failure_stage=ACTION_FAILURE_STAGE_RUNNING_FAILED,
        failure_message_public=ACTION_FAILURE_MESSAGE_CANCELED,
        error_payload=None,
        final_output=None,
        memory_draft_json=None,
    )


def read_nonterminal_child_process_ids(
    connection: sqlite3.Connection,
    *,
    user_id: str,
    action_id: str,
    parent_process_id: str,
) -> tuple[str, ...]:
    """Read every child of the parent that can still mutate the Action."""

    rows = connection.execute(
        _NONTERMINAL_CHILDREN_SQL,
        (user_id, action_id, parent_process_id, ACTION_SUBAGENT_PROCESS_KIND),
    ).fetchall()
    return tuple(str(row[0]) for row in rows)


def read_active_child_claim_ids(
    connection: sqlite3.Connection,
    *,
    user_id: str,
    action_id: str,
    parent_process_id: str,
) -> tuple[str, ...]:
    """Read every resource claim the parent's children still hold."""

    rows = connection.execute(
        _ACTIVE_CLAIM_IDS_SQL,
        (user_id, action_id, parent_process_id),
    ).fetchall()
    return tuple(str(row[0]) for row in rows)


def _live_children(
    connection: sqlite3.Connection,
    command: FinalizeActionTerminalCommand,
) -> tuple[str, ...]:
    return read_nonterminal_child_process_ids(
        connection,
        user_id=command.user_id,
        action_id=command.action_id,
        parent_process_id=command.process_id,
    )
