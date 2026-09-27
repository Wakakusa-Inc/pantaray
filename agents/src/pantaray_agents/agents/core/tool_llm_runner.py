"""ツール内部の LLM 呼び出し専用 runner。"""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel

from pantaray_agents.agents.core.mixins.llm_generation_mixin import LLMGenerationMixin
from pantaray_agents.agents.core.mixins.llm_usage import TokenSink


@dataclass(frozen=True, slots=True)
class StructuredLlmResult[ResponseT]:
    text: str
    parsed: ResponseT


class ToolLlmRunner(LLMGenerationMixin):
    """ツール内部専用の薄い LLM runner。"""

    def __init__(
        self,
        *,
        client: object,
        llm_config: dict[str, object],
        default_system_instruction: str,
        error_code_prefix: str,
        llm_inference_profile_id: str,
    ) -> None:
        self.client = client
        self.llm_config = dict(llm_config)
        self.DEFAULT_SYSTEM_INSTRUCTION = default_system_instruction
        self._error_code_prefix = error_code_prefix
        self.LLM_INFERENCE_PROFILE_ID = llm_inference_profile_id

    def get_error_code_prefix(self) -> str:
        return self._error_code_prefix

    async def generate_text(
        self,
        *,
        sink: TokenSink,
        prompt: str,
        system_instruction: str | None = None,
        stage: str | None = None,
    ) -> str:
        response = await self._generate_llm_response(
            prompt=prompt,
            sink=sink,
            system_instruction=system_instruction,
            stage=stage,
        )
        if not isinstance(response, str):
            raise TypeError("Tool LLM runner expected a text response.")
        return response

    async def generate_structured[ResponseT: BaseModel](
        self,
        *,
        sink: TokenSink,
        prompt: str,
        response_model: type[ResponseT],
        response_schema: object | None = None,
        system_instruction: str | None = None,
        stage: str | None = None,
    ) -> StructuredLlmResult[ResponseT]:
        """Generate and validate a response against an explicit schema type."""

        text, parsed = await self._generate_llm_structured(
            prompt=prompt,
            sink=sink,
            response_schema=(
                response_model if response_schema is None else response_schema
            ),
            system_instruction=system_instruction,
            stage=stage,
        )
        if isinstance(parsed, response_model):
            validated = parsed
        else:
            try:
                validated = response_model.model_validate(parsed)
            except ValueError as exc:
                raise TypeError(
                    "Tool LLM runner returned an invalid structured response."
                ) from exc
        return StructuredLlmResult(text=text, parsed=validated)


__all__ = ["StructuredLlmResult", "ToolLlmRunner"]
