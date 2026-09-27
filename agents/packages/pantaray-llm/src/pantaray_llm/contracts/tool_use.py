from __future__ import annotations

from typing import Annotated, Literal

from jsonschema import Draft7Validator  # type: ignore[import-untyped]
from jsonschema.exceptions import SchemaError  # type: ignore[import-untyped]
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SerializerFunctionWrapHandler,
    model_serializer,
    model_validator,
)

from pantaray_llm.contracts.conversation import LlmConversation
from pantaray_llm.contracts.json_value import JSONValue
from pantaray_llm.contracts.media import LlmMediaProjection
from pantaray_llm.contracts.tool_call import LlmToolCall, LlmToolResult


class LlmToolDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=64)
    description: str = Field(min_length=1)
    parameters: dict[str, JSONValue]

    @model_validator(mode="after")
    def validate_parameters_schema(self) -> LlmToolDefinition:
        if self.parameters.get("type") != "object":
            raise ValueError("tool parameters must describe an object")
        try:
            Draft7Validator.check_schema(self.parameters)
        except SchemaError as exc:
            raise ValueError(
                f"tool parameters schema is invalid: {exc.message}"
            ) from exc
        return self


def validate_tool_names(tools: list[LlmToolDefinition]) -> list[str]:
    names = [tool.name for tool in tools]
    if len(set(names)) != len(names):
        raise ValueError("tool names must be unique")
    return names


class OpenAiContinuationMediaSlot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item_index: int = Field(ge=0)
    content_index: int = Field(ge=0)
    data_field: Literal["image_url"]
    projection: LlmMediaProjection


class OpenAiToolContinuation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: Literal["openai"]
    history_items: list[dict[str, JSONValue]] = Field(min_length=1)
    media_slots: list[OpenAiContinuationMediaSlot] = Field(default_factory=list)


class AnthropicToolContinuation(BaseModel):
    """The Messages API conversation that produced the pending tool calls.

    Anthropic reads an assistant turn back only byte for byte: a thinking block
    without its signature, a redacted_thinking block without its data, or a
    reordered block is rejected. So the items stay as the wire delivered them
    instead of being rebuilt from the parsed response.

    Media stays inline in these items, unlike the OpenAI continuation, which
    strips it into ``media_slots`` and re-materializes it per turn. That strip
    exists because the OpenAI continuation crosses the cloud request wire beside
    the same bytes as multipart parts, and because its adapter refits media to a
    byte budget every turn. The Anthropic adapter does neither, and no caller
    sends media on a stateless request, so carrying the items as sent is both
    smaller and lossless.
    """

    model_config = ConfigDict(extra="forbid")

    provider: Literal["anthropic"]
    messages: list[dict[str, JSONValue]] = Field(min_length=1)


# The discriminator keeps the OpenAI member's wire shape byte for byte: Pantaray
# Cloud and already-distributed desktops exchange `provider: "openai"` today.
type LlmToolContinuation = Annotated[
    OpenAiToolContinuation | AnthropicToolContinuation,
    Field(discriminator="provider"),
]


class LlmToolUseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tools: list[LlmToolDefinition] = Field(min_length=1)
    continuation_mode: Literal["disabled", "stateless"]
    continuation: LlmToolContinuation | None = None
    tool_result: LlmToolResult | None = None
    max_parallel_tool_calls: int = Field(default=1, ge=1)
    # Absent: the adapter sends the request's own user message and nothing else.
    # Present: those items follow that message, in order -- the same structure an
    # Action turn sends, so a caller that keeps its own transcript replays it
    # here instead of rebuilding one string per turn.
    conversation: LlmConversation | None = None

    @model_validator(mode="after")
    def validate_continuation_pair(self) -> LlmToolUseRequest:
        has_continuation = self.continuation is not None
        has_result = self.tool_result is not None
        if has_continuation != has_result:
            raise ValueError("continuation and tool_result must be provided together")
        if has_continuation and self.continuation_mode != "stateless":
            raise ValueError("continuation requires stateless continuation_mode")
        if self.conversation is not None:
            # A conversation already holds every earlier turn, including the calls
            # and the results that answered them, so a caller sending one has no
            # provider history to resume and no single pending call to answer.
            if has_continuation:
                raise ValueError("conversation and continuation are exclusive")
            if self.continuation_mode != "disabled":
                raise ValueError("conversation requires disabled continuation_mode")
        # A continuation carries one provider history whose last function_call must be
        # answered by exactly one tool_result, so a batch could only ever be resumed
        # with partial results.
        if self.max_parallel_tool_calls > 1 and self.continuation_mode != "disabled":
            raise ValueError(
                "max_parallel_tool_calls above 1 requires disabled continuation_mode"
            )
        names = validate_tool_names(self.tools)
        if self.tool_result is not None and self.tool_result.name not in names:
            raise ValueError("tool_result.name must reference a declared tool")
        return self

    @model_serializer(mode="wrap")
    def serialize_without_absent_conversation(
        self, handler: SerializerFunctionWrapHandler
    ) -> dict[str, object]:
        """Serialize a request that carries no conversation exactly as before.

        Pantaray Cloud validates this contract with ``extra="forbid"``, and a
        deployed Cloud that predates ``conversation`` rejects the key whatever
        it holds -- ``null`` included. Every tool-use request goes this way,
        Insight and memory updates and Suggestion included, so the key is
        dropped here rather than in any one caller.
        """

        payload: dict[str, object] = handler(self)
        if self.conversation is None:
            payload.pop("conversation", None)
        return payload


class LlmToolUseResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    calls: list[LlmToolCall] = Field(min_length=1)
    dropped_call_names: list[str] = Field(default_factory=list)
    continuation: LlmToolContinuation | None = None

    @property
    def call(self) -> LlmToolCall:
        return self.calls[0]


LlmToolUseRequest.model_rebuild()
LlmToolUseResponse.model_rebuild()


__all__ = [
    "AnthropicToolContinuation",
    "LlmToolCall",
    "LlmToolContinuation",
    "LlmToolDefinition",
    "LlmToolResult",
    "LlmToolUseRequest",
    "LlmToolUseResponse",
    "OpenAiContinuationMediaSlot",
    "OpenAiToolContinuation",
    "validate_tool_names",
]
