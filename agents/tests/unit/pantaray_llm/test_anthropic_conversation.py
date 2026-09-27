"""Action の中立な会話が Messages API の messages 列になることを確かめる。"""

from __future__ import annotations

from collections.abc import Callable

import pytest
from tests.unit.pantaray_llm.test_anthropic_provider import (
    _TOOL,
    _blobs,
    _descriptor,
    _execute,
    _install,
    _message,
    _ok,
    _profile,
    _request,
    _tool_block,
)

from pantaray_llm.errors import ProviderError

_USER_MESSAGE = {"role": "user", "content": [{"type": "text", "text": "hi"}]}
_SIGNED_BLOCKS: list[dict[str, object]] = [
    {"type": "thinking", "thinking": "step", "signature": "sig-1"},
    {"type": "redacted_thinking", "data": "encrypted-1"},
    {"type": "server_tool_use", "id": "srvtoolu_1"},
    {"type": "tool_use", "id": "toolu_9", "name": "lookup", "input": {"id": "z"}},
]


def _assistant(**overrides: object) -> dict[str, object]:
    return {
        "type": "assistant",
        "text": ["Looking it up."],
        "calls": [{"call_id": "toolu_1", "name": "lookup", "arguments": {"id": "a"}}],
        **overrides,
    }


def _result(call_id: str = "toolu_1", **overrides: object) -> dict[str, object]:
    return {
        "type": "tool_result",
        "call_id": call_id,
        "name": "lookup",
        "output": {"status": "ok", "値": "見つかった"},
        **overrides,
    }


def _turn(conversation: list[dict[str, object]] | None = None) -> dict[str, object]:
    tool_use: dict[str, object] = {
        "mode": "action_turn",
        "tools": [_TOOL],
        "max_parallel_tool_calls": 3,
    }
    if conversation is not None:
        tool_use["conversation"] = conversation
    return tool_use


def _tool_use(conversation: list[dict[str, object]]) -> dict[str, object]:
    """The same conversation, sent by a ReAct loop instead of the Action agent."""

    return {
        "tools": [_TOOL],
        "continuation_mode": "disabled",
        "conversation": conversation,
    }


@pytest.mark.asyncio
async def test_each_assistant_item_opens_a_turn_answered_by_the_next_user_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _install(monkeypatch, _ok(_message(content=[_tool_block()])))

    await _execute(
        _request(
            tool_use=_turn(
                [
                    {
                        "type": "user",
                        "content": [{"type": "input_text", "text": "start"}],
                    },
                    _assistant(),
                    _result(),
                    _assistant(
                        text=[],
                        calls=[
                            {
                                "call_id": "toolu_2",
                                "name": "lookup",
                                "arguments": {"id": "b"},
                            }
                        ],
                    ),
                    _result("toolu_2", output="plain"),
                    {
                        "type": "user",
                        "content": [{"type": "input_text", "text": "now"}],
                    },
                ]
            )
        )
    )

    assert calls[0]["body"]["messages"] == [
        _USER_MESSAGE,
        {"role": "user", "content": [{"type": "text", "text": "start"}]},
        {
            "role": "assistant",
            "content": [
                {"type": "text", "text": "Looking it up."},
                {
                    "type": "tool_use",
                    "id": "toolu_1",
                    "name": "lookup",
                    "input": {"id": "a"},
                },
            ],
        },
        {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": "toolu_1",
                    "content": '{"status": "ok", "値": "見つかった"}',
                }
            ],
        },
        {
            "role": "assistant",
            "content": [
                {
                    "type": "tool_use",
                    "id": "toolu_2",
                    "name": "lookup",
                    "input": {"id": "b"},
                },
            ],
        },
        {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": "toolu_2",
                    "content": '"plain"',
                },
                {"type": "text", "text": "now"},
            ],
        },
    ]


@pytest.mark.asyncio
async def test_parallel_results_share_one_user_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _install(monkeypatch, _ok(_message(content=[_tool_block()])))
    parallel_calls = [
        {"call_id": f"toolu_{index}", "name": "lookup", "arguments": {"id": "a"}}
        for index in (1, 2, 3)
    ]

    await _execute(
        _request(
            tool_use=_turn(
                [
                    _assistant(text=[], calls=parallel_calls),
                    _result("toolu_1"),
                    _result("toolu_2"),
                    _result("toolu_3"),
                ]
            )
        )
    )

    answer = calls[0]["body"]["messages"][-1]
    assert answer["role"] == "user"
    assert [block["tool_use_id"] for block in answer["content"]] == [
        "toolu_1",
        "toolu_2",
        "toolu_3",
    ]


@pytest.mark.asyncio
async def test_a_stored_turn_is_replayed_block_for_block(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _install(monkeypatch, _ok(_message(content=[_tool_block()])))

    await _execute(
        _request(
            tool_use=_turn(
                [
                    _assistant(
                        provider_turn={
                            "provider": "anthropic",
                            "blocks": _SIGNED_BLOCKS,
                        }
                    ),
                    _result(),
                ]
            )
        )
    )

    # Signatures, redacted payloads and unknown block types all survive, and the
    # ids the model signed are the ones sent, not the neutral items' call ids.
    assert calls[0]["body"]["messages"][1] == {
        "role": "assistant",
        "content": _SIGNED_BLOCKS,
    }


@pytest.mark.asyncio
async def test_another_providers_turn_is_dropped_and_the_structure_rebuilt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _install(monkeypatch, _ok(_message(content=[_tool_block()])))

    await _execute(
        _request(
            tool_use=_turn(
                [
                    _assistant(
                        provider_turn={
                            "provider": "openai",
                            "items": [{"type": "reasoning", "id": "rs_1"}],
                        }
                    ),
                    _result(),
                ]
            )
        )
    )

    assert calls[0]["body"]["messages"][1] == {
        "role": "assistant",
        "content": [
            {"type": "text", "text": "Looking it up."},
            {
                "type": "tool_use",
                "id": "toolu_1",
                "name": "lookup",
                "input": {"id": "a"},
            },
        ],
    }


@pytest.mark.asyncio
async def test_a_tool_results_attachment_rides_inside_its_result_block(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _install(monkeypatch, _ok(_message(content=[_tool_block()])))

    await _execute(
        _request(
            tool_use=_turn(
                [
                    _assistant(),
                    _result(
                        output="captured",
                        content=[
                            {"type": "input_image", "image": _descriptor("image/png")}
                        ],
                    ),
                ]
            )
        ),
        profile=_profile(enable_image_inputs=True),
        uploaded_blobs=_blobs("image/png"),
    )

    # The upload is only accepted because the tool result referenced it; an
    # unreferenced blob is rejected before the request is sent.
    result = calls[0]["body"]["messages"][-1]["content"][0]
    assert result["content"][0] == {"type": "text", "text": '"captured"'}
    assert result["content"][1]["type"] == "image"
    assert result["content"][1]["source"]["media_type"] == "image/png"


@pytest.mark.asyncio
@pytest.mark.parametrize("build_tool_use", [_turn, _tool_use])
async def test_a_conversation_ending_on_an_assistant_item_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
    build_tool_use: Callable[[list[dict[str, object]]], dict[str, object]],
) -> None:
    calls = _install(monkeypatch, _ok(_message(content=[_tool_block()])))

    with pytest.raises(ProviderError) as exc_info:
        await _execute(_request(tool_use=build_tool_use([_assistant()])))

    assert exc_info.value.code == "PROXY_INVALID_INPUT"
    assert calls == []


@pytest.mark.asyncio
async def test_a_tool_use_request_sends_its_conversation_the_same_way(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _install(
        monkeypatch,
        _ok(_message(content=[_tool_block()], stop_reason="tool_use")),
    )

    response = await _execute(_request(tool_use=_tool_use([_assistant(), _result()])))

    assert calls[0]["body"]["messages"] == [
        _USER_MESSAGE,
        {
            "role": "assistant",
            "content": [
                {"type": "text", "text": "Looking it up."},
                {
                    "type": "tool_use",
                    "id": "toolu_1",
                    "name": "lookup",
                    "input": {"id": "a"},
                },
            ],
        },
        {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": "toolu_1",
                    "content": '{"status": "ok", "値": "見つかった"}',
                }
            ],
        },
    ]
    # Only an Action turn keeps a provider turn to replay.
    assert response.provider_turn is None


@pytest.mark.asyncio
async def test_the_turn_comes_back_for_a_caller_that_sent_a_conversation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    content = [*_SIGNED_BLOCKS[:3], _tool_block()]
    _install(monkeypatch, _ok(_message(content=content, stop_reason="tool_use")))

    response = await _execute(_request(tool_use=_turn([_assistant(), _result()])))

    assert response.provider_turn.provider == "anthropic"
    assert response.provider_turn.blocks == content
    assert response.tool_use.calls[0].call_id == "toolu_1"


@pytest.mark.asyncio
async def test_an_action_turn_without_a_conversation_sends_and_answers_as_before(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _install(
        monkeypatch,
        _ok(_message(content=[_tool_block()], stop_reason="tool_use")),
    )

    response = await _execute(_request(tool_use=_turn()))

    assert calls[0]["body"]["messages"] == [_USER_MESSAGE]
    assert response.provider_turn is None


@pytest.mark.asyncio
async def test_a_rejected_turn_hands_back_no_blocks_to_replay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    content = [_tool_block(name="unknown")]
    _install(monkeypatch, _ok(_message(content=content, stop_reason="tool_use")))

    response = await _execute(_request(tool_use=_turn([_assistant(), _result()])))

    assert response.meta.outcome == "model_output_rejected"
    assert response.provider_turn is None
