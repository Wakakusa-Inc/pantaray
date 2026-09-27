"""Memory Agent trigger for a completed 24h Activity Summary.

Every successful daily summary is evidence for the unified Memory run: what it
says about the day may change a Fact, an Insight, or nothing at all, and only
the run can decide. There is no eligibility gate, so the replay path requires
the trigger the success path created.
"""

from __future__ import annotations

import sqlite3

from .memory_agent_triggers import (
    SUMMARY_MEMORY_TRIGGER_KIND,
    insert_pending_memory_agent_trigger,
    require_memory_agent_trigger,
)

_DAILY_SUMMARY_TYPE = "24h"


def create_activity_summary_trigger_if_eligible(
    *,
    connection: sqlite3.Connection,
    user_id: str,
    summary_id: str,
    summary_type: str,
    succeeded_at: str,
) -> None:
    if summary_type != _DAILY_SUMMARY_TYPE:
        return
    insert_pending_memory_agent_trigger(
        connection=connection,
        user_id=user_id,
        trigger_kind=SUMMARY_MEMORY_TRIGGER_KIND,
        source_id=summary_id,
        created_at=succeeded_at,
    )


def require_activity_summary_replay_trigger(
    *,
    connection: sqlite3.Connection,
    user_id: str,
    summary_id: str,
    summary_type: str,
) -> None:
    if summary_type != _DAILY_SUMMARY_TYPE:
        return
    require_memory_agent_trigger(
        connection=connection,
        user_id=user_id,
        trigger_kind=SUMMARY_MEMORY_TRIGGER_KIND,
        source_id=summary_id,
    )


__all__ = [
    "create_activity_summary_trigger_if_eligible",
    "require_activity_summary_replay_trigger",
]
