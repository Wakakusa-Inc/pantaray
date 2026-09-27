"""Decide whether one Action can still open a follow-up turn.

A follow-up turn continues from the checkpoint the Action's latest run left, so
it can only start while that checkpoint is one this build restores. The runtime
refuses any other version outright, so a turn accepted without this predicate
would fail on its first step. This module is the single owner of the predicate:
the USER message boundary enforces it, and the conversation read model reports
it as ``resumable`` once the Action's latest intent is the user's Stop.
"""

from __future__ import annotations

import sqlite3

from pantaray_agents.agents.action_agent.runtime.checkpoint import (
    RUNTIME_STATE_CHECKPOINT_VERSION,
)


def action_latest_run_has_restorable_checkpoint(
    *,
    connection: sqlite3.Connection,
    user_id: str,
    action_id: str,
) -> bool:
    """Say whether the Action's latest run left a checkpoint this build restores."""

    row = connection.execute(
        """
        SELECT EXISTS (
            SELECT 1
            FROM agent_action_steps AS checkpoints
            WHERE checkpoints.user_id = :user_id
              AND checkpoints.action_id = :action_id
              AND checkpoints.runtime_state_checkpoint_version = :checkpoint_version
              AND checkpoints.step_number >= (
                  SELECT MAX(user_steps.step_number)
                  FROM agent_action_steps AS user_steps
                  WHERE user_steps.user_id = :user_id
                    AND user_steps.action_id = :action_id
                    AND user_steps.step_type = 'user_request'
                    AND user_steps.status = 'success'
              )
        )
        """,
        {
            "user_id": user_id,
            "action_id": action_id,
            "checkpoint_version": RUNTIME_STATE_CHECKPOINT_VERSION,
        },
    ).fetchone()
    return bool(row[0])


__all__ = ["action_latest_run_has_restorable_checkpoint"]
