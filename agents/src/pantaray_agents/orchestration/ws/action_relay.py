"""Action WS event dispatch responsibilities."""

from __future__ import annotations

import asyncio

from pantaray_agents.action_status import ActionTerminalStatus
from pantaray_agents.orchestration.ws.action_error_meta import (
    ActionErrorMeta,
    ActionErrorStage,
)
from pantaray_agents.schema.websocket.server_messages import (
    ErrorMessage,
)

from . import action_relay_emit_ops as emit_ops
from . import action_relay_forwarder_ops as forwarder_ops
from .action_relay_process import ActionRelayProcessMixin
from .action_relay_shared import ACTION_EVENT_CURSOR_START_ID

__all__ = ["ACTION_EVENT_CURSOR_START_ID", "ActionRelayMixin"]


class ActionRelayMixin(ActionRelayProcessMixin):
    """Action event dispatch responsibilities."""

    def _build_action_error_meta(
        self,
        *,
        suggestion_id: str,
        command_id: str,
        action_stage: ActionErrorStage,
        error_code: str,
        process_id: str | None = None,
        action_id: str | None = None,
        failure_kind: str | None = None,
    ) -> ActionErrorMeta:
        return emit_ops._build_action_error_meta(
            self,
            suggestion_id=suggestion_id,
            command_id=command_id,
            action_stage=action_stage,
            error_code=error_code,
            process_id=process_id,
            action_id=action_id,
            failure_kind=failure_kind,
        )

    async def _send_action_error(
        self,
        message: ErrorMessage,
        *,
        suggestion_id: str,
        command_id: str,
        action_stage: ActionErrorStage,
        process_id: str | None = None,
        action_id: str | None = None,
        failure_kind: str | None = None,
        event_id: str | None = None,
        store_in_session_store: bool = True,
        persist_public_event: bool = True,
        persisted_sequence_override: int | None = None,
    ) -> None:
        return await emit_ops._send_action_error(
            self,
            message,
            suggestion_id=suggestion_id,
            command_id=command_id,
            action_stage=action_stage,
            process_id=process_id,
            action_id=action_id,
            failure_kind=failure_kind,
            event_id=event_id,
            store_in_session_store=store_in_session_store,
            persist_public_event=persist_public_event,
            persisted_sequence_override=persisted_sequence_override,
        )

    async def _release_action_start_resources(self, *, process_id: str) -> None:
        return await emit_ops._release_action_start_resources(
            self, process_id=process_id
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
        return await emit_ops._attach_action_process_to_current_session(
            self,
            process_id=process_id,
            logical_run_id=logical_run_id,
            suggestion_id=suggestion_id,
            action_id=action_id,
            command_id=command_id,
            start_event_id=start_event_id,
            start_after_cursor=start_after_cursor,
        )

    async def _emit_action_requested(
        self,
        *,
        suggestion_id: str,
        command_id: str,
        accepted_at: str,
    ) -> None:
        return await emit_ops._emit_action_requested(
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
        return await emit_ops._replay_action_requested(
            self,
            suggestion_id=suggestion_id,
            command_id=command_id,
            accepted_at=accepted_at,
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
        return await emit_ops._emit_process_started_action(
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
        return await emit_ops._replay_process_started_action(
            self,
            process_id=process_id,
            suggestion_id=suggestion_id,
            action_id=action_id,
            command_id=command_id,
            accepted_at=accepted_at,
            started_at=started_at,
            event_id=event_id,
            store_in_session_store=store_in_session_store,
            persisted_sequence_override=persisted_sequence_override,
        )

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
        return await emit_ops._emit_process_completed_action(
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
        return emit_ops._record_action_terminal_completion_once(
            self, process_id=process_id, status=status
        )

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
        return forwarder_ops._start_action_event_forwarder(
            self,
            process_id=process_id,
            logical_run_id=logical_run_id,
            suggestion_id=suggestion_id,
            action_id=action_id,
            command_id=command_id,
            start_event_id=start_event_id,
            start_after_cursor=start_after_cursor,
        )
