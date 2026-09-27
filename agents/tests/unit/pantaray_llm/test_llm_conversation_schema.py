from __future__ import annotations

import pytest
from pydantic import ValidationError
from tests.unit.pantaray_llm.test_llm_tool_use_schema import _tool

from pantaray_llm.contracts.action_turn import LlmActionTurnRequest
from pantaray_llm.contracts.conversation import (
    AnthropicProviderTurn,
    LlmTurnAssistantItem,
)
from pantaray_llm.contracts.request import LlmProxyRequest, LlmProxyResponse

# Encrypted reasoning as the Responses API delivers it: keys this contract never
# names, a nested structure, and every JSON scalar.
_OPENAI_ITEMS: list[dict[str, object]] = [
    {
        "type": "reasoning",
        "id": "rs_1",
        "encrypted_content": "gAAAAAB…",
        "summary": [],
        "nested": {"ints": [1, 0], "float": 2.5, "flag": True, "missing": None},
    },
    {"type": "function_call", "id": "fc_1", "call_id": "call-1", "name": "completed"},
]
_ANTHROPIC_BLOCKS: list[dict[str, object]] = [
    {"type": "thinking", "thinking": "…", "signature": "EqoBCkgIAR…"},
    {"type": "redacted_thinking", "data": "EmwKAhgBEgy…"},
]
_OPENAI_TURN: dict[str, object] = {"provider": "openai", "items": _OPENAI_ITEMS}
_ANTHROPIC_TURN: dict[str, object] = {
    "provider": "anthropic",
    "blocks": _ANTHROPIC_BLOCKS,
}
_TOOL_RESULT: dict[str, object] = {
    "type": "tool_result",
    "call_id": "call-1",
    "name": "completed",
    "output": None,
    "content": [{"type": "input_text", "text": "添付"}],
}


def _conversation(
    *, provider_turn: dict[str, object] | None = None
) -> list[dict[str, object]]:
    assistant: dict[str, object] = {
        "type": "assistant",
        "text": ["まず調べます。"],
        "calls": [{"call_id": "call-1", "name": "completed", "arguments": {"x": 1}}],
        "provider_turn": provider_turn,
    }
    return [
        {"type": "user", "content": [{"type": "input_text", "text": "調べて"}]},
        assistant,
        _TOOL_RESULT,
    ]


def _request(conversation: list[dict[str, object]] | None) -> dict[str, object]:
    payload: dict[str, object] = {
        "mode": "action_turn",
        "tools": [_tool().model_dump(mode="json")],
        "max_parallel_tool_calls": 1,
    }
    if conversation is not None:
        payload["conversation"] = conversation
    return payload


def _envelope(tool_use: dict[str, object]) -> dict[str, object]:
    return {
        "inference_profile": "action.executing",
        "messages": [
            {"role": "user", "content": [{"type": "input_text", "text": "調べて"}]}
        ],
        "metadata": {
            "request_kind": "llm_inference",
            "user_id": "user-1",
            "local_job_id": "job-1",
            "session_version": "1",
        },
        "tool_use": tool_use,
    }


def _serialized_tool_use(tool_use: dict[str, object]) -> object:
    envelope = LlmProxyRequest.model_validate(_envelope(tool_use))
    return envelope.model_dump(mode="json")["tool_use"]


def test_action_turn_without_conversation_keeps_the_deployed_cloud_wire() -> None:
    """A request that sets no conversation must not name the field at all.

    Pantaray Cloud validates this envelope with ``extra="forbid"``, so a
    ``"conversation": null`` reaching a Cloud deployed before this contract
    fails every cloud-routed Action turn with a 400. The envelope is checked
    too: the caller dumps the nested model, not the bare one.
    """

    bare = _request(None)
    request = LlmActionTurnRequest.model_validate(bare)
    assert request.conversation is None
    assert request.model_dump(mode="json") == bare
    assert _serialized_tool_use(bare) == bare


@pytest.mark.parametrize("provider_turn", [None, _OPENAI_TURN, _ANTHROPIC_TURN])
def test_conversation_round_trips_every_item_and_opaque_payload(
    provider_turn: dict[str, object] | None,
) -> None:
    """Both adapters read this wire back, so nothing may be rewritten in transit."""

    wire = _request(_conversation(provider_turn=provider_turn))
    assert LlmActionTurnRequest.model_validate(wire).model_dump(mode="json") == wire
    assert _serialized_tool_use(wire) == wire


@pytest.mark.parametrize(
    ("conversation", "message"),
    [
        pytest.param([], "at least 1 item", id="empty-conversation"),
        pytest.param(
            [_TOOL_RESULT], "answers no preceding tool call", id="result-without-call"
        ),
        pytest.param(
            [*_conversation(), _TOOL_RESULT],
            "is answered twice",
            id="result-answered-twice",
        ),
        pytest.param(
            [{"type": "assistant", "text": [], "calls": []}],
            "text or tool calls",
            id="assistant-says-nothing",
        ),
        pytest.param(
            [{"type": "assistant", "text": [""]}],
            "at least 1 character",
            id="assistant-empty-text-block",
        ),
        pytest.param(
            [{"type": "user", "content": []}], "at least 1 item", id="empty-user-item"
        ),
        pytest.param(
            [{"type": "reasoning", "text": ["…"]}],
            "does not match any of the expected tags",
            id="unknown-item-type",
        ),
    ],
)
def test_conversation_rejects_turns_no_provider_accepts(
    conversation: list[dict[str, object]], message: str
) -> None:
    with pytest.raises(ValidationError, match=message):
        LlmActionTurnRequest.model_validate(_request(conversation))


@pytest.mark.parametrize(
    "conversation",
    [
        pytest.param(
            [
                {
                    "type": "user",
                    "role": "user",
                    "content": [{"type": "input_text", "text": "調べて"}],
                }
            ],
            id="user",
        ),
        pytest.param(
            [{"type": "assistant", "text": ["…"], "thinking": "…"}], id="assistant"
        ),
        pytest.param([{**_TOOL_RESULT, "is_error": True}], id="tool-result"),
        pytest.param(
            [
                {
                    "type": "assistant",
                    "text": ["…"],
                    "provider_turn": {**_OPENAI_TURN, "model": "gpt-6-luna"},
                }
            ],
            id="provider-turn",
        ),
    ],
)
def test_conversation_items_reject_unknown_keys(
    conversation: list[dict[str, object]],
) -> None:
    """A misspelled field must fail loudly instead of crossing the wire dropped."""

    with pytest.raises(ValidationError, match="Extra inputs"):
        LlmActionTurnRequest.model_validate(_request(conversation))


def test_provider_turn_variant_is_chosen_by_its_tag_alone() -> None:
    """A mislabelled turn must fail, not fall through to the other provider."""

    item = LlmTurnAssistantItem.model_validate(
        {"type": "assistant", "text": ["…"], "provider_turn": _ANTHROPIC_TURN}
    )
    assert isinstance(item.provider_turn, AnthropicProviderTurn)
    with pytest.raises(ValidationError, match="Extra inputs"):
        LlmTurnAssistantItem.model_validate(
            {
                "type": "assistant",
                "text": ["…"],
                "provider_turn": {"provider": "anthropic", "items": _OPENAI_ITEMS},
            }
        )


def _response(provider_turn: dict[str, object] | None) -> dict[str, object]:
    payload: dict[str, object] = {
        "model": "fixture-model",
        "output": [],
        "meta": {
            "local_job_id": "job-1",
            "upstream_provider": "openai",
            "profile_id": "action.executing",
            "outcome": "complete",
        },
    }
    if provider_turn is not None:
        payload["provider_turn"] = provider_turn
    return payload


@pytest.mark.parametrize("provider_turn", [None, _OPENAI_TURN])
def test_proxy_response_carries_the_provider_turn_at_the_top_level(
    provider_turn: dict[str, object] | None,
) -> None:
    """Every provider still builds a valid response, with or without a turn."""

    response = LlmProxyResponse.model_validate(_response(provider_turn))
    assert LlmProxyResponse.model_validate_json(response.model_dump_json()) == response
    assert response.model_dump(mode="json", exclude_none=True) == _response(
        provider_turn
    )
