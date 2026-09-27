"""Action relay forwarder dispatchers."""

from __future__ import annotations

import asyncio

from . import action_relay_forwarder_local as local_forwarder


def _start_action_event_forwarder(
    self,
    *,
    process_id: str,
    logical_run_id: str,
    suggestion_id: str | None,
    action_id: str,
    command_id: str,
    start_event_id: str,
    start_after_cursor: int = 0,
) -> asyncio.Task[None] | None:
    del start_event_id
    task_key = f"action_event_forwarder:{process_id}"
    spawn = getattr(self, "_spawn_background_task", None)
    if not callable(spawn):
        return
    return spawn(
        task_key=task_key,
        coro=local_forwarder._forward_action_events_from_local_runtime(
            self,
            process_id=process_id,
            logical_run_id=logical_run_id,
            suggestion_id=suggestion_id,
            action_id=action_id,
            command_id=command_id,
            start_after_cursor=start_after_cursor,
        ),
    )
