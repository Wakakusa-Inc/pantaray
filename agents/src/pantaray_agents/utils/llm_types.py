from __future__ import annotations

from dataclasses import dataclass

from pantaray_llm.contracts.action_turn import LlmActionTurnRequest
from pantaray_llm.contracts.tool_use import LlmToolUseRequest


@dataclass(frozen=True, slots=True)
class UploadFileConfig:
    mime_type: str


@dataclass(frozen=True, slots=True)
class GenerateContentConfig:
    inference_profile: str | None = None
    system_instruction: str | None = None
    response_mime_type: str | None = None
    response_schema: object | None = None
    tool_use: LlmToolUseRequest | LlmActionTurnRequest | None = None


class _TypesNamespace:
    UploadFileConfig = UploadFileConfig
    GenerateContentConfig = GenerateContentConfig


types = _TypesNamespace()


__all__ = [
    "GenerateContentConfig",
    "UploadFileConfig",
    "types",
]
