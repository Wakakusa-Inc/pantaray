from __future__ import annotations

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from pantaray_llm.contracts.action_turn import (
    LlmActionTurnRequest,
    LlmActionTurnResponse,
)
from pantaray_llm.contracts.conversation import LlmProviderTurn
from pantaray_llm.contracts.input_block import LlmImageDescriptor as LlmImageDescriptor
from pantaray_llm.contracts.input_block import LlmInputBlock
from pantaray_llm.contracts.input_block import LlmInputImageBlock as LlmInputImageBlock
from pantaray_llm.contracts.input_block import LlmInputTextBlock as LlmInputTextBlock
from pantaray_llm.contracts.json_value import JSONValue
from pantaray_llm.contracts.tool_use import LlmToolUseRequest, LlmToolUseResponse
from pantaray_llm.errors import (
    LlmProvider,
    ProxyResultOutcome,
    ToolCallViolationReason,
)

type LlmMessageRole = Literal["system", "user"]


class LlmMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: LlmMessageRole
    content: list[LlmInputBlock] = Field(min_length=1)


class LlmProxyRequestMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_kind: Literal["llm_inference"]
    user_id: str = Field(min_length=1)
    local_job_id: str = Field(min_length=1)
    session_version: str = Field(min_length=1)


class LlmJsonSchemaResponseFormat(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["json_schema"]
    json_schema: dict[str, JSONValue]


class _LlmRequestContent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    messages: list[LlmMessage] = Field(min_length=1)
    response_format: LlmJsonSchemaResponseFormat | None = None
    tool_use: LlmToolUseRequest | LlmActionTurnRequest | None = None
    # 呼び出し元が固定するキャッシュキー（action 単位）。provider へそのまま渡す。
    prompt_cache_key: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def validate_output_contract(self) -> Self:
        if self.response_format is not None and self.tool_use is not None:
            raise ValueError("response_format and tool_use are mutually exclusive")
        return self


class LlmRequestTrace(BaseModel):
    model_config = ConfigDict(extra="forbid")

    local_job_id: str = Field(min_length=1)


class LlmRequest(_LlmRequestContent):
    purpose: str = Field(min_length=1)
    trace: LlmRequestTrace


class LlmProxyRequest(_LlmRequestContent):
    inference_profile: str = Field(min_length=1)
    metadata: LlmProxyRequestMetadata

    def to_request(self) -> LlmRequest:
        # The cloud envelope already validated the shared content at ingress.
        return LlmRequest.model_construct(
            purpose=self.inference_profile,
            trace=LlmRequestTrace.model_construct(
                local_job_id=self.metadata.local_job_id
            ),
            messages=self.messages,
            response_format=self.response_format,
            tool_use=self.tool_use,
            prompt_cache_key=self.prompt_cache_key,
        )


class LlmOutputTextBlock(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["output_text"] = "output_text"
    text: str


class LlmOutputMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Literal["assistant"] = "assistant"
    content: list[LlmOutputTextBlock]


class LlmUsagePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prompt_tokens: int
    cached_prompt_tokens: int = 0
    cache_write_prompt_tokens: int = 0
    completion_tokens: int
    # completion_tokens の内訳（足し戻さない）。内訳を返さないプロバイダーでは 0。
    reasoning_tokens: int = 0
    total_tokens: int


class LlmProxyResultMeta(BaseModel):
    model_config = ConfigDict(extra="forbid")

    local_job_id: str = Field(min_length=1)
    upstream_provider: LlmProvider
    profile_id: str = Field(min_length=1)
    outcome: ProxyResultOutcome
    upstream_request_id: str | None = None
    resolved_model: str | None = None


class LlmModelOutputError(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: Literal["PROXY_LLM_TOOL_CALL_INVALID"]
    message: str = Field(min_length=1)
    recovery: Literal["repair_next_turn", "stop"]
    violation_reason: ToolCallViolationReason
    actual_tool_call_count: int | None = None
    tool_name: str | None = None
    response_status: str | None = None
    argument_path: str | None = None
    schema_keyword: str | None = None


class LlmProxyResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str | None = None
    model: str
    output: list[LlmOutputMessage]
    tool_use: LlmToolUseResponse | LlmActionTurnResponse | None = None
    # The Action turn's output items, to hand back on the next turn. This sits
    # at the top level because distributed desktops read the top level of a
    # response leniently -- they pull known keys off the raw object and ignore
    # the rest -- while `tool_use` is validated against a closed contract.
    provider_turn: LlmProviderTurn | None = None
    thinking: str | None = None
    finish_reason: str | None = None
    usage: LlmUsagePayload | None = None
    meta: LlmProxyResultMeta
    model_error: LlmModelOutputError | None = None

    @model_validator(mode="after")
    def validate_model_error_outcome(self) -> LlmProxyResponse:
        rejected = self.meta.outcome == "model_output_rejected"
        if rejected != (self.model_error is not None):
            raise ValueError(
                "model_output_rejected outcome and model_error must be present together"
            )
        if rejected and (self.output or self.tool_use is not None):
            raise ValueError("model-rejected responses cannot contain usable output")
        return self


LlmJsonSchemaResponseFormat.model_rebuild()
LlmRequest.model_rebuild()
LlmProxyRequest.model_rebuild()
