"""Action relay shared types and validators."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final, Literal, NotRequired, TypedDict

from pantaray_agents.action_status import (
    ActionTerminalStatus,
    is_action_terminal_status,
)
from pantaray_agents.orchestration.common.types import EventPayload

ACTION_EVENT_CURSOR_START_ID = "0-0"
_ZERO_UUID = "00000000-0000-0000-0000-000000000000"
_STREAM_ID_PATTERN = re.compile(r"^\d+-\d+$")
_ACTION_FORWARDER_RETRY_INITIAL_DELAY_SECONDS = 1.0
_ACTION_FORWARDER_RETRY_MAX_DELAY_SECONDS = 10.0
_ACTION_STREAM_PAYLOAD_INVALID_ERROR_CODE = "ACTION_STREAM_PAYLOAD_INVALID"
_ACTION_STREAM_PAYLOAD_INVALID_ERROR_MESSAGE = "Action stream payload is invalid."
_ACTION_STREAM_PAYLOAD_INVALID_REVOKE_TERMINATE: Final[bool] = True
_ACTION_START_FAILURE_REVOKE_TERMINATE: Final[bool] = True


class _StreamEndStreamData(TypedDict):
    status: ActionTerminalStatus
    persisted_sequence: NotRequired[int]
    physical_run_only: NotRequired[Literal[True]]
    final_output: NotRequired[str]
    failure_code: NotRequired[str]
    failure_stage: NotRequired[str]
    failure_message_public: NotRequired[str]


@dataclass(frozen=True)
class _ActionStreamTerminalizationResult:
    terminal_status: ActionTerminalStatus
    terminal_event_id: str | None
    error_event_id: str | None = None
    emit_invalid_payload_error: bool = False
    emit_process_completed: bool = True


class ActionStreamPayloadValidationError(ValueError):
    """Action event payload が契約を満たさない場合の明示エラー。"""


def _require_stream_mapping(raw: object, *, event_name: str) -> EventPayload:
    if not isinstance(raw, dict):
        raise ActionStreamPayloadValidationError(
            f"{event_name} payload must be an object"
        )
    payload: EventPayload = {}
    for key, value in raw.items():
        if not isinstance(key, str):
            raise ActionStreamPayloadValidationError(
                f"{event_name} payload keys must be strings"
            )
        payload[key] = value
    return payload


def _require_stream_string(
    payload: EventPayload,
    *,
    event_name: str,
    field_name: str,
) -> str:
    value = payload.get(field_name)
    if not isinstance(value, str):
        raise ActionStreamPayloadValidationError(
            f"{event_name}.{field_name} must be a string"
        )
    return value


def _validate_stream_end_stream_data(raw: object) -> _StreamEndStreamData:
    payload = _require_stream_mapping(raw, event_name="stream_end")
    status = _require_stream_string(
        payload, event_name="stream_end", field_name="status"
    )
    if not is_action_terminal_status(status):
        raise ActionStreamPayloadValidationError(
            "stream_end.status must be a terminal action status"
        )
    validated: _StreamEndStreamData = {"status": status}
    persisted_sequence = payload.get("persisted_sequence")
    if persisted_sequence is not None:
        if not isinstance(persisted_sequence, int) or isinstance(
            persisted_sequence, bool
        ):
            raise ActionStreamPayloadValidationError(
                "stream_end.persisted_sequence must be an integer"
            )
        validated["persisted_sequence"] = persisted_sequence
    if "physical_run_only" in payload:
        if payload["physical_run_only"] is not True or persisted_sequence is not None:
            raise ActionStreamPayloadValidationError(
                "stream_end.physical_run_only must be true without persisted_sequence"
            )
        validated["physical_run_only"] = True
    for field_name in (
        "final_output",
        "failure_code",
        "failure_stage",
        "failure_message_public",
    ):
        value = payload.get(field_name)
        if value is None:
            continue
        if not isinstance(value, str):
            raise ActionStreamPayloadValidationError(
                f"stream_end.{field_name} must be a string when present"
            )
        normalized_value = value.strip()
        if normalized_value:
            validated[field_name] = normalized_value
    if validated.get("physical_run_only") and (
        status != "canceled"
        or "final_output" in validated
        or any(
            field_name not in validated
            for field_name in (
                "failure_code",
                "failure_stage",
                "failure_message_public",
            )
        )
    ):
        raise ActionStreamPayloadValidationError(
            "physical-run-only stream_end must contain canceled failure detail"
        )
    return validated
