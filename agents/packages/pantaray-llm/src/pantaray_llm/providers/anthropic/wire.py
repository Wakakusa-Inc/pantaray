"""Anthropic Messages API の要求ブロックと応答本文の型。"""

from __future__ import annotations

import base64
from typing import Annotated, Literal

from pydantic import AliasPath, BaseModel, Field, field_validator

from pantaray_llm.contracts.json_value import JSONValue
from pantaray_llm.contracts.request import LlmUsagePayload
from pantaray_llm.contracts.uploaded_blob import UploadedBlob


class AnthropicTextBlock(BaseModel):
    type: Literal["text"]
    text: str


class AnthropicThinkingBlock(BaseModel):
    type: Literal["thinking"]
    thinking: str


class AnthropicRedactedThinkingBlock(BaseModel):
    type: Literal["redacted_thinking"]


class AnthropicToolUseBlock(BaseModel):
    type: Literal["tool_use"]
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    input: dict[str, JSONValue]


_KNOWN_BLOCK_TYPES = frozenset({"text", "thinking", "redacted_thinking", "tool_use"})


class AnthropicOtherBlock(BaseModel):
    """未知の content ブロック。text にも thinking にも寄与しない。"""

    type: str

    @field_validator("type")
    @classmethod
    def reject_known_block_types(cls, value: str) -> str:
        # 既知の型は厳密に解く。壊れた既知ブロックをここで受けてしまうと、
        # 読み飛ばした結果の部分出力が完全な応答として返ってしまう。
        if value in _KNOWN_BLOCK_TYPES:
            raise ValueError(f"malformed {value} content block")
        return value


# Anthropic は versioning 方針上あとから content ブロックを増やせる。未知の型で応答
# 全体を落とすと usage まで失うので、既知の型だけを解いて残りは読み飛ばす。
type AnthropicContentBlock = (
    Annotated[
        AnthropicTextBlock
        | AnthropicThinkingBlock
        | AnthropicRedactedThinkingBlock
        | AnthropicToolUseBlock,
        Field(discriminator="type"),
    ]
    | AnthropicOtherBlock
)


class AnthropicUsage(BaseModel):
    input_tokens: int
    output_tokens: int
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0


class AnthropicMessageResponse(BaseModel):
    type: Literal["message"]
    id: str = Field(min_length=1)
    model: str = Field(min_length=1)
    content: list[AnthropicContentBlock]
    # The same blocks as they arrived. A continuation has to replay an assistant
    # turn unmodified, and the typed view above drops what it does not declare:
    # a thinking block's signature, a redacted_thinking block's data, and every
    # field of a block type this version does not know.
    raw_content: list[JSONValue] = Field(validation_alias=AliasPath("content"))
    stop_reason: str | None = None
    usage: AnthropicUsage

    def text(self) -> str:
        return "".join(
            block.text
            for block in self.content
            if isinstance(block, AnthropicTextBlock)
        )

    def thinking(self) -> str | None:
        thinking = "".join(
            block.thinking
            for block in self.content
            if isinstance(block, AnthropicThinkingBlock)
        )
        return thinking or None


def anthropic_usage_payload(usage: AnthropicUsage) -> LlmUsagePayload:
    # Anthropic の 3 つの入力カウントは互いに素（input_tokens はキャッシュ分を含まない）。
    # 共有契約の prompt_tokens はプロンプト全体なので、キャッシュ分を足し戻す。
    prompt_tokens = (
        usage.input_tokens
        + usage.cache_read_input_tokens
        + usage.cache_creation_input_tokens
    )
    return LlmUsagePayload(
        prompt_tokens=prompt_tokens,
        cached_prompt_tokens=usage.cache_read_input_tokens,
        cache_write_prompt_tokens=usage.cache_creation_input_tokens,
        completion_tokens=usage.output_tokens,
        total_tokens=prompt_tokens + usage.output_tokens,
    )


def anthropic_media_block(*, blob: UploadedBlob) -> dict[str, JSONValue]:
    return {
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": blob.mime_type,
            "data": base64.b64encode(blob.payload).decode("ascii"),
        },
    }
