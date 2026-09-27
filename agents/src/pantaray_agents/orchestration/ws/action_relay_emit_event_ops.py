"""Action relay event emission helpers."""

from __future__ import annotations

from pantaray_agents.action_status import ACTION_STATUS_SUCCESS, ActionTerminalStatus
from pantaray_agents.schema.events import OutboundEvent
from pantaray_agents.schema.websocket.server_messages import (
    ActionProcessCompletedReplayMessage,
    ProcessStartedMessage,
)
from pantaray_agents.utils.metrics import record_action_job_completed


async def _send_action_requested(
    self,
    *,
    suggestion_id: str,
    command_id: str,
    accepted_at: str,
    persist_public_event: bool = True,
    persisted_sequence_override: int | None = None,
) -> None:
    await self.emit_action_requested(
        suggestion_id=suggestion_id,
        command_id=command_id,
        accepted_at=accepted_at,
        committed_at=accepted_at,
        meta={
            "suggestion_id": suggestion_id,
            "command_id": command_id,
            "kind": "action",
        },
        persist_public_event=persist_public_event,
        persisted_sequence_override=persisted_sequence_override,
    )


async def _emit_action_requested(
    self,
    *,
    suggestion_id: str,
    command_id: str,
    accepted_at: str,
) -> None:
    await _send_action_requested(
        self,
        suggestion_id=suggestion_id,
        command_id=command_id,
        accepted_at=accepted_at,
    )


async def _replay_action_requested(
    self,
    *,
    suggestion_id: str,
    command_id: str,
    accepted_at: str,
    persisted_sequence_override: int | None = None,
) -> None:
    await _send_action_requested(
        self,
        suggestion_id=suggestion_id,
        command_id=command_id,
        accepted_at=accepted_at,
        persist_public_event=False,
        persisted_sequence_override=persisted_sequence_override,
    )


async def _send_process_started_action(
    self,
    *,
    process_id: str,
    suggestion_id: str | None,
    action_id: str,
    command_id: str,
    accepted_at: str,
    started_at: str,
    event_id: str | None = None,
    store_in_session_store: bool = True,
    persist_public_event: bool = True,
    persisted_sequence_override: int | None = None,
) -> bool:
    return await self._send(
        OutboundEvent.PROCESS_STARTED.value,
        ProcessStartedMessage(
            kind="action",
            process_id=process_id,
            suggestion_id=suggestion_id,
            action_id=action_id,
            command_id=command_id,
            accepted_at=accepted_at,
            started_at=started_at,
        ),
        process_id=process_id,
        meta={
            "process_id": process_id,
            "suggestion_id": suggestion_id,
            "action_id": action_id,
            "command_id": command_id,
            "kind": "action",
        },
        event_id=event_id,
        store_in_session_store=store_in_session_store,
        persist_public_event=persist_public_event,
        persisted_sequence_override=persisted_sequence_override,
    )


async def _emit_process_started_action(
    self,
    *,
    process_id: str,
    suggestion_id: str | None,
    action_id: str,
    command_id: str,
    accepted_at: str,
    started_at: str,
    event_id: str | None = None,
    store_in_session_store: bool = True,
    persist_public_event: bool = True,
    persisted_sequence_override: int | None = None,
) -> bool:
    return await _send_process_started_action(
        self,
        process_id=process_id,
        suggestion_id=suggestion_id,
        action_id=action_id,
        command_id=command_id,
        accepted_at=accepted_at,
        started_at=started_at,
        event_id=event_id,
        store_in_session_store=store_in_session_store,
        persist_public_event=persist_public_event,
        persisted_sequence_override=persisted_sequence_override,
    )


async def _replay_process_started_action(
    self,
    *,
    process_id: str,
    suggestion_id: str | None,
    action_id: str,
    command_id: str,
    accepted_at: str,
    started_at: str,
    event_id: str | None = None,
    store_in_session_store: bool = True,
    persisted_sequence_override: int | None = None,
) -> bool:
    return await _send_process_started_action(
        self,
        process_id=process_id,
        suggestion_id=suggestion_id,
        action_id=action_id,
        command_id=command_id,
        accepted_at=accepted_at,
        started_at=started_at,
        event_id=event_id,
        store_in_session_store=store_in_session_store,
        persist_public_event=False,
        persisted_sequence_override=persisted_sequence_override,
    )


async def _send_process_completed_action(
    self,
    *,
    process_id: str,
    suggestion_id: str | None,
    action_id: str,
    command_id: str,
    status: ActionTerminalStatus,
    event_id: str | None = None,
    store_in_session_store: bool = True,
    persisted_sequence_override: int | None = None,
) -> bool:
    message = ActionProcessCompletedReplayMessage(
        kind="action",
        process_id=process_id,
        suggestion_id=suggestion_id,
        action_id=action_id,
        command_id=command_id,
        status=status,
    )
    sent = await self._send(
        OutboundEvent.PROCESS_COMPLETED.value,
        message,
        process_id=process_id,
        meta={
            "process_id": process_id,
            "suggestion_id": suggestion_id,
            "action_id": action_id,
            "command_id": command_id,
            "kind": "action",
        },
        event_id=event_id,
        store_in_session_store=store_in_session_store,
        persist_public_event=False,
        persisted_sequence_override=persisted_sequence_override,
    )
    if sent:
        record_action_job_completed(status=status)
    return sent


async def _emit_process_completed_action(
    self,
    *,
    process_id: str,
    suggestion_id: str | None,
    action_id: str,
    command_id: str,
    status: ActionTerminalStatus,
    event_id: str | None = None,
    store_in_session_store: bool = True,
    persisted_sequence_override: int | None = None,
) -> bool:
    try:
        self._sync_process_metadata_to_current_session(
            process_id,
            suggestion_id=suggestion_id,
            action_id=action_id,
            command_id=command_id,
            kind="action",
        )
    except ValueError:
        return False
    return await _send_process_completed_action(
        self,
        process_id=process_id,
        suggestion_id=suggestion_id,
        action_id=action_id,
        command_id=command_id,
        status=status,
        event_id=event_id,
        store_in_session_store=store_in_session_store,
        persisted_sequence_override=persisted_sequence_override,
    )


def _record_action_terminal_completion_once(
    self,
    *,
    process_id: str,
    status: ActionTerminalStatus,
) -> None:
    self.session_store.mark_process_completion_emitted(
        self.session_id,
        process_id,
        status=status,
    )
    completed = getattr(self, "_action_completed", None)
    if not isinstance(completed, set):
        completed = set()
        self._action_completed = completed  # type: ignore[attr-defined]
    if process_id in completed:
        return
    completed.add(process_id)
    if status == ACTION_STATUS_SUCCESS:
        self._action_last_terminal_success = True
