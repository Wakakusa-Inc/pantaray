"""Action relay error helpers."""

from __future__ import annotations

from pantaray_agents.schema.events import OutboundEvent
from pantaray_agents.schema.websocket.server_messages import ErrorMessage

from .action_error_meta import ActionErrorMeta, ActionErrorStage


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
    meta: ActionErrorMeta = {
        "kind": "action",
        "suggestion_id": str(suggestion_id),
        "command_id": str(command_id),
        "stage": action_stage,
        "error_code": str(error_code),
    }
    if process_id:
        meta["process_id"] = str(process_id)
    if action_id:
        meta["action_id"] = str(action_id)
    if failure_kind:
        meta["failure_kind"] = str(failure_kind)
    return meta


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
    meta = _build_action_error_meta(
        self,
        suggestion_id=suggestion_id,
        command_id=command_id,
        action_stage=action_stage,
        error_code=message.error_code,
        process_id=process_id,
        action_id=action_id,
        failure_kind=failure_kind,
    )
    await self._send(
        OutboundEvent.ERROR.value,
        message,
        process_id=process_id,
        meta=dict(meta),
        event_id=event_id,
        store_in_session_store=store_in_session_store,
        persist_public_event=persist_public_event,
        persisted_sequence_override=persisted_sequence_override,
    )
