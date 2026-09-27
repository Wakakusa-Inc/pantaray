"""Build the Messages API `messages` array for one request.

A native turn reaches this module either as the caller's single user message
-- the shape every turn had before a conversation existed -- or as that message
followed by the structured conversation the caller projected. Laying the
conversation out is the whole reason this module is separate from the provider:
Messages has placement rules (tool_result blocks open the user message that
directly follows the assistant turn asking for them, parallel results share one
message) that the neutral item list does not carry.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import cast

from pantaray_llm.contracts.action_turn import LlmActionTurnRequest
from pantaray_llm.contracts.conversation import (
    AnthropicProviderTurn,
    LlmConversation,
    LlmTurnAssistantItem,
    LlmTurnToolResultItem,
)
from pantaray_llm.contracts.json_value import JSONValue
from pantaray_llm.contracts.request import (
    LlmInputBlock,
    LlmInputTextBlock,
    LlmMessageRole,
    LlmRequest,
)
from pantaray_llm.contracts.tool_use import LlmToolUseRequest
from pantaray_llm.contracts.uploaded_blob import UploadedBlob
from pantaray_llm.errors import PROXY_INVALID_INPUT, ProviderError
from pantaray_llm.providers.anthropic.settings import AnthropicLlmProfile
from pantaray_llm.providers.anthropic.tool_use import resume_anthropic_messages
from pantaray_llm.providers.anthropic.transport import ANTHROPIC_MAX_REQUEST_BYTES
from pantaray_llm.providers.anthropic.wire import anthropic_media_block
from pantaray_llm.providers.uploaded_content import (
    request_too_large_error,
    require_uploaded_blob,
)

_USER_ROLE: LlmMessageRole = "user"
_ASSISTANT_ROLE = "assistant"


def anthropic_invalid_input(message: str) -> ProviderError:
    return ProviderError(status_code=400, code=PROXY_INVALID_INPUT, message=message)


def build_anthropic_messages(
    *,
    request: LlmRequest,
    profile: AnthropicLlmProfile,
    uploaded_blobs: Mapping[str, UploadedBlob],
    tool_use: LlmToolUseRequest | LlmActionTurnRequest | None,
) -> tuple[list[dict[str, JSONValue]], set[str]]:
    """Build the conversation: the caller's turn, a resumed one, or a projected one.

    A resumed turn replays the continuation instead of the caller's prompt. The
    ReAct callers resend the same prompt every turn and the continuation already
    holds it, so sending it again would repeat it to the model. A conversation
    is the other way of carrying that history, and the contract keeps the two
    apart, so it follows the caller's prompt on either request type.
    """

    if isinstance(tool_use, LlmToolUseRequest):
        continuation = tool_use.continuation
        tool_result = tool_use.tool_result
        # The contract pairs a continuation with its tool_result, or neither.
        if continuation is not None and tool_result is not None:
            return (
                resume_anthropic_messages(
                    continuation=continuation, tool_result=tool_result
                ),
                set(),
            )
    media = _RequestMedia(profile=profile, uploaded_blobs=uploaded_blobs)
    messages: list[dict[str, JSONValue]] = [
        {"role": _USER_ROLE, "content": cast(JSONValue, _user_content(request, media))}
    ]
    if tool_use is not None and tool_use.conversation is not None:
        messages.extend(_conversation_messages(tool_use.conversation, media))
    return messages, media.referenced_blob_refs


def _user_content(request: LlmRequest, media: _RequestMedia) -> list[JSONValue]:
    messages = [message for message in request.messages if message.role == _USER_ROLE]
    if len(messages) != 1:
        raise anthropic_invalid_input("LLM proxy requires exactly one user message.")
    return media.blocks(messages[0].content)


def _conversation_messages(
    conversation: LlmConversation, media: _RequestMedia
) -> list[dict[str, JSONValue]]:
    """Lay the neutral items out as alternating Messages API turns.

    An assistant item opens a new assistant message. Everything else belongs to
    the user message between two assistant messages: consecutive tool results
    share it, because Messages requires one message to answer a turn's parallel
    calls, and a user item that follows them joins the same message behind the
    results, because tool_result blocks must come first in the content array.
    """

    if isinstance(conversation[-1], LlmTurnAssistantItem):
        # Messages would read a trailing assistant turn as a prefill to extend,
        # which current models reject outright, and its calls would have no
        # results. Say so here rather than pay for the upstream 400.
        raise anthropic_invalid_input("A conversation cannot end on an assistant item.")
    messages: list[dict[str, JSONValue]] = []
    results: list[JSONValue] = []
    blocks: list[JSONValue] = []

    def flush_user_message() -> None:
        if results or blocks:
            messages.append(
                {"role": _USER_ROLE, "content": cast(JSONValue, [*results, *blocks])}
            )
            results.clear()
            blocks.clear()

    for item in conversation:
        if isinstance(item, LlmTurnAssistantItem):
            flush_user_message()
            messages.append(
                {"role": _ASSISTANT_ROLE, "content": _assistant_content(item)}
            )
        elif isinstance(item, LlmTurnToolResultItem):
            results.append(_tool_result_block(item, media))
        else:
            blocks.extend(media.blocks(item.content))
    flush_user_message()
    return messages


def _assistant_content(item: LlmTurnAssistantItem) -> JSONValue:
    provider_turn = item.provider_turn
    if isinstance(provider_turn, AnthropicProviderTurn):
        # The turn goes back exactly as it arrived: a thinking block without its
        # signature, a redacted_thinking block without its data, or a reordered
        # block is rejected, and the ids the results answer are the ones here.
        return cast(JSONValue, provider_turn.blocks)
    # Absent, or another provider's turn, which this adapter never replays: the
    # structure still goes back, only the opaque reasoning is lost.
    content: list[JSONValue] = [{"type": "text", "text": text} for text in item.text]
    content.extend(
        {
            "type": "tool_use",
            "id": call.call_id,
            "name": call.name,
            "input": call.arguments,
        }
        for call in item.calls
    )
    return content


def _tool_result_block(
    item: LlmTurnToolResultItem, media: _RequestMedia
) -> dict[str, JSONValue]:
    # The same text the OpenAI adapter puts in function_call_output and the
    # stateless continuation puts in its tool_result, so the model reads one
    # tool result the same way on every path.
    output = json.dumps(item.output, ensure_ascii=False)
    content: JSONValue = output
    if item.content:
        # Messages accepts text and image blocks inside a tool_result, which
        # keeps an attachment attached to the result that produced it.
        content = [{"type": "text", "text": output}, *media.blocks(item.content)]
    return {
        "type": "tool_result",
        "tool_use_id": item.call_id,
        "content": content,
    }


@dataclass(slots=True)
class _RequestMedia:
    """One request's media budget, shared by every block that can carry media.

    The leading user message and the conversation's tool results draw on the
    same request-size limit and the same multipart uploads, so the running total
    and the set of blobs actually referenced live here rather than per caller.
    """

    profile: AnthropicLlmProfile
    uploaded_blobs: Mapping[str, UploadedBlob]
    referenced_blob_refs: set[str] = field(default_factory=set)
    encoded_media_bytes: int = 0

    def blocks(self, content: Sequence[LlmInputBlock]) -> list[JSONValue]:
        blocks: list[JSONValue] = []
        for block in content:
            if isinstance(block, LlmInputTextBlock):
                blocks.append({"type": "text", "text": block.text})
                continue
            if not self.profile.enable_image_inputs:
                raise anthropic_invalid_input(
                    f"Anthropic profile does not accept image inputs: "
                    f"{self.profile.profile_id}."
                )
            descriptor = block.image
            # base64 は 3 バイトを 4 文字にし、同じ blob を何度参照しても毎回符号化される。
            # 符号化前に累計を確かめて、記述子だけ小さい要求でのメモリ膨張を止める。
            self.encoded_media_bytes += descriptor.byte_size * 4 // 3
            if self.encoded_media_bytes > ANTHROPIC_MAX_REQUEST_BYTES:
                raise request_too_large_error(
                    request_size_bytes=self.encoded_media_bytes,
                    max_request_bytes=ANTHROPIC_MAX_REQUEST_BYTES,
                    reason="media_references_too_large",
                )
            blob = require_uploaded_blob(
                descriptor=descriptor, uploaded_blobs=self.uploaded_blobs
            )
            blocks.append(anthropic_media_block(blob=blob))
            self.referenced_blob_refs.add(descriptor.blob_ref)
        return blocks


__all__ = [
    "anthropic_invalid_input",
    "build_anthropic_messages",
]
