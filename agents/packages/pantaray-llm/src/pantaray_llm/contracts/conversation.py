"""Provider-neutral conversation items for one turn of a tool-using loop.

An Action turn reaches its provider as a single rendered string today, so every
turn is a different prompt prefix and no prompt cache ever reads: measured over
171 turns on the live API, ``cached_tokens`` was zero on every one. These items
keep the turn's structure instead -- who spoke, which call produced which result
-- and each adapter lays that structure out the way its own provider reads a
conversation.

The structure is worth sending whether or not the provider's own reasoning can
be replayed, so the opaque ``provider_turn`` is optional on every assistant item
and is simply absent when the turn cannot be handed back.

Both native request contracts carry these items: ``LlmActionTurnRequest`` for
the Action agent, ``LlmToolUseRequest`` for the ReAct loops that keep their own
transcript, so one projection and one pair of adapters serve both.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator

from pantaray_llm.contracts.input_block import LlmInputBlock
from pantaray_llm.contracts.json_value import JSONValue
from pantaray_llm.contracts.tool_call import LlmToolCall, LlmToolResult


class OpenAiProviderTurn(BaseModel):
    """The output items one Responses turn produced, held as they arrived.

    The items keep a wide JSON type because the provider, not this contract,
    validates what comes back: a ``reasoning`` item's ``encrypted_content`` is
    readable only by the organization that issued it, and the pairing between a
    ``reasoning`` item and the ``function_call`` that follows it is checked
    upstream. Modelling the fields would mean re-describing every key the API
    sends today and every key it adds later, and one dropped or reordered field
    is a rejected request. So nothing here reads or rewrites them.
    """

    model_config = ConfigDict(extra="forbid")

    provider: Literal["openai"]
    items: list[dict[str, JSONValue]] = Field(min_length=1)


class AnthropicProviderTurn(BaseModel):
    """The content blocks of one assistant turn, held as they arrived.

    Anthropic reads an assistant turn back only byte for byte -- a thinking
    block without its signature, or a redacted block without its data, is
    rejected -- so these blocks keep the same wide JSON type and the same
    hands-off treatment as ``OpenAiProviderTurn.items``.
    """

    model_config = ConfigDict(extra="forbid")

    provider: Literal["anthropic"]
    blocks: list[dict[str, JSONValue]] = Field(min_length=1)


# Separate from ``LlmToolContinuation``: a continuation replays one call and one
# result, which cannot express a turn that called several tools at once.
type LlmProviderTurn = Annotated[
    OpenAiProviderTurn | AnthropicProviderTurn,
    Field(discriminator="provider"),
]


class LlmTurnUserItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["user"]
    content: list[LlmInputBlock] = Field(min_length=1)


class LlmTurnAssistantItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["assistant"]
    # An empty string is not a block either provider will accept.
    text: list[Annotated[str, Field(min_length=1)]] = Field(default_factory=list)
    calls: list[LlmToolCall] = Field(default_factory=list)
    provider_turn: LlmProviderTurn | None = None

    @model_validator(mode="after")
    def validate_nonempty_turn(self) -> LlmTurnAssistantItem:
        if not self.text and not self.calls:
            raise ValueError("an assistant item must contain text or tool calls")
        return self


class LlmTurnToolResultItem(LlmToolResult):
    """One tool's result, plus whatever media that tool attached to it."""

    type: Literal["tool_result"]
    content: list[LlmInputBlock] = Field(default_factory=list)


type LlmTurnItem = Annotated[
    LlmTurnUserItem | LlmTurnAssistantItem | LlmTurnToolResultItem,
    Field(discriminator="type"),
]


def _validate_call_pairing(items: list[LlmTurnItem]) -> list[LlmTurnItem]:
    """Keep every tool result attached to a call the assistant actually made.

    A result whose call never appeared, or a second result for the same call,
    is rejected outright by both providers, so the turn would fail after the
    desktop had already paid to send it.

    Nothing here demands that every call has a result: a run that stops for an
    approval sends the calls it made and answers the outstanding ones with
    synthesized results, which the projection decides, not this contract.
    """

    announced: set[str] = set()
    answered: set[str] = set()
    for item in items:
        if isinstance(item, LlmTurnAssistantItem):
            announced.update(call.call_id for call in item.calls)
        elif isinstance(item, LlmTurnToolResultItem):
            if item.call_id not in announced:
                raise ValueError(
                    f"tool result {item.call_id} answers no preceding tool call"
                )
            if item.call_id in answered:
                raise ValueError(f"tool result {item.call_id} is answered twice")
            answered.add(item.call_id)
    return items


# Absent is the only way to say "no conversation", so an empty list is invalid.
type LlmConversation = Annotated[
    list[LlmTurnItem],
    Field(min_length=1),
    AfterValidator(_validate_call_pairing),
]


__all__ = [
    "AnthropicProviderTurn",
    "LlmConversation",
    "LlmProviderTurn",
    "LlmTurnAssistantItem",
    "LlmTurnItem",
    "LlmTurnToolResultItem",
    "LlmTurnUserItem",
    "OpenAiProviderTurn",
]
