from __future__ import annotations

import base64

import pytest
from pydantic import BaseModel, ConfigDict, NonNegativeInt, TypeAdapter

from pantaray_agents.local_runtime.action_conversation.cursor import (
    SQLITE_INTEGER_MAX,
    ActionConversationRunBoundary,
    ActionConversationTimelineCursor,
    ActionConversationUnadoptedCursor,
    ActionConversationUnadoptedFrontier,
    decode_action_conversation_cursor,
    encode_action_conversation_cursor,
)
from pantaray_agents.local_runtime.action_conversation.cursor_codec import (
    OpaqueCursorError,
    decode_opaque_cursor,
    encode_opaque_cursor,
)


class _ToolOutputCursor(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    action_id: str
    step_id: str
    next_byte_offset: NonNegativeInt


_TOOL_OUTPUT_CURSOR_ADAPTER = TypeAdapter(_ToolOutputCursor)
_CURRENT_CEILING = ActionConversationRunBoundary(
    run_id="run-current", step_number=12, step_id="step-12"
)


@pytest.mark.parametrize(
    "payload",
    [
        ActionConversationTimelineCursor(
            user_id="user-1",
            action_id="action-1",
            scope="current_timeline",
            step_number=12,
            step_id="step-12",
            timeline_ceiling=_CURRENT_CEILING,
        ),
        ActionConversationUnadoptedCursor(
            user_id="user-1",
            action_id="action-1",
            scope="unadopted",
            accepted_sequence=15,
            step_id="step-pending",
            timeline_boundary=ActionConversationRunBoundary(
                run_id="run-current",
                step_number=10,
                step_id="step-current",
            ),
            timeline_ceiling=ActionConversationRunBoundary(
                run_id="run-current",
                step_number=12,
                step_id="step-latest",
            ),
            unadopted_ceiling=ActionConversationUnadoptedFrontier(
                accepted_sequence=15,
                step_id="step-pending",
            ),
        ),
        ActionConversationTimelineCursor(
            user_id="user-1",
            action_id="action-1",
            scope="older_timeline",
            step_number=4,
            step_id="step-4",
            timeline_ceiling=None,
        ),
    ],
)
def test_history_cursor_preserves_scope_sort_key_and_exact_anchor(
    payload: ActionConversationTimelineCursor | ActionConversationUnadoptedCursor,
) -> None:
    cursor = encode_action_conversation_cursor(payload)

    assert "=" not in cursor
    assert decode_action_conversation_cursor(cursor) == payload


def test_codec_reuses_a_strict_tool_output_payload() -> None:
    payload = _ToolOutputCursor(
        action_id="action-1",
        step_id="step-9",
        next_byte_offset=16_384,
    )
    cursor = encode_opaque_cursor(payload, adapter=_TOOL_OUTPUT_CURSOR_ADAPTER)

    assert decode_opaque_cursor(cursor, adapter=_TOOL_OUTPUT_CURSOR_ADAPTER) == payload


@pytest.mark.parametrize(
    "payload_json",
    [
        b'{"user_id":"user-1","action_id":"action-1","scope":"current_timeline","step_number":"12","step_id":"step-12"}',
        b'{"user_id":"user-1","action_id":"action-1","scope":"current_timeline","step_number":12,"step_id":"step-12","extra":true}',
        b'{"user_id":"user-1","action_id":"action-1","scope":"unadopted","step_number":12,"step_id":"step-12"}',
        (
            b'{"user_id":"user-1","action_id":"action-1","scope":"current_timeline",'
            + f'"step_number":{SQLITE_INTEGER_MAX + 1},"step_id":"step-12"}}'.encode()
        ),
        (
            b'{"user_id":"user-1","action_id":"action-1","scope":"unadopted",'
            + f'"accepted_sequence":{SQLITE_INTEGER_MAX + 1},"step_id":"step-12"}}'.encode()
        ),
    ],
)
def test_history_cursor_rejects_untrusted_payload_shapes(payload_json: bytes) -> None:
    cursor = base64.urlsafe_b64encode(payload_json).rstrip(b"=").decode()

    with pytest.raises(OpaqueCursorError, match="malformed or non-canonical"):
        decode_action_conversation_cursor(cursor)


def test_history_cursor_rejects_malformed_and_noncanonical_encodings() -> None:
    payload = ActionConversationTimelineCursor(
        user_id="user-1",
        action_id="action-1",
        scope="current_timeline",
        step_number=12,
        step_id="step-12",
        timeline_ceiling=_CURRENT_CEILING,
    )
    canonical = encode_action_conversation_cursor(payload)
    spaced_json = b" " + payload.model_dump_json().encode()
    spaced = base64.urlsafe_b64encode(spaced_json).rstrip(b"=").decode()

    for cursor in (canonical + "=", spaced, "not*a*cursor"):
        with pytest.raises(OpaqueCursorError, match="malformed or non-canonical"):
            decode_action_conversation_cursor(cursor)
