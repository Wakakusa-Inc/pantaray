"""Action relay start-resource helpers."""

from __future__ import annotations

import asyncio
import logging

from pantaray_agents.local_runtime.runtime.bootstrap import (
    is_local_runtime_enabled,  # noqa: F401
    read_local_runtime_db_config,
)
from pantaray_agents.local_runtime.runtime.process_events import (
    resolve_local_process_event_cursor,
)
from pantaray_agents.orchestration.ws.action_relay_shared import (
    ACTION_EVENT_CURSOR_START_ID,
)

logger = logging.getLogger(__name__)


class ActionResumeCursorUnavailable(RuntimeError):
    """Raised when a requested action resume cursor cannot be resolved."""


async def _release_action_start_resources(self, *, process_id: str) -> None:
    self._release_action_process(process_id)
    try:
        self.session_store.clear_process(self.session_id, process_id)
    except Exception:
        logger.exception("Failed to clear Action process from the WebSocket session")


def _resolve_start_after_cursor(*, process_id: str, start_event_id: str) -> int | None:
    if not start_event_id or start_event_id == ACTION_EVENT_CURSOR_START_ID:
        return 0
    db_path, busy_timeout_ms = read_local_runtime_db_config()
    return resolve_local_process_event_cursor(
        db_path=db_path,
        busy_timeout_ms=busy_timeout_ms,
        process_id=process_id,
        event_id=start_event_id,
    )


async def _attach_action_process_to_current_session(
    self,
    *,
    process_id: str,
    logical_run_id: str,
    suggestion_id: str | None,
    action_id: str,
    command_id: str,
    start_event_id: str,
    start_after_cursor: int | None = None,
) -> asyncio.Task[None] | None:
    resolved_start_after_cursor = (
        _resolve_start_after_cursor(
            process_id=process_id,
            start_event_id=start_event_id,
        )
        if start_after_cursor is None
        else int(start_after_cursor)
    )
    if resolved_start_after_cursor is None:
        raise ActionResumeCursorUnavailable("action resume cursor is not available")
    self._bind_action_process(process_id, suggestion_id, action_id)
    self._sync_process_metadata_to_current_session(
        process_id,
        suggestion_id=suggestion_id,
        action_id=action_id,
        kind="action",
        command_id=command_id,
    )
    return self._start_action_event_forwarder(
        process_id=process_id,
        logical_run_id=logical_run_id,
        suggestion_id=suggestion_id,
        action_id=str(action_id),
        command_id=command_id,
        start_event_id=start_event_id,
        start_after_cursor=resolved_start_after_cursor,
    )
