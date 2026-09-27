"""Small helpers for action session resume."""

from __future__ import annotations

from pantaray_agents.local_runtime.runtime.bootstrap import read_local_runtime_db_config
from pantaray_agents.local_runtime.runtime.process_events import (
    resolve_local_process_event_cursor,
)
from pantaray_agents.orchestration.ws.action_relay import ACTION_EVENT_CURSOR_START_ID


def resolve_action_start_after_cursor(
    *,
    process_id: str,
    last_cursor: str | None,
) -> int | None:
    normalized_cursor = str(last_cursor or "").strip()
    if not normalized_cursor or normalized_cursor == ACTION_EVENT_CURSOR_START_ID:
        return 0
    db_path, busy_timeout_ms = read_local_runtime_db_config()
    return resolve_local_process_event_cursor(
        db_path=db_path,
        busy_timeout_ms=busy_timeout_ms,
        process_id=process_id,
        event_id=normalized_cursor,
    )
