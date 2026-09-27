"""One tool call, and the result that answers it.

These sit below both ``tool_use`` and ``conversation``: a tool-use request
answers one pending call, and a conversation's assistant item announces the
calls its tool-result items answer -- the same pair, named the same way. So the
pair owns its own module and neither contract imports the other. ``tool_use``
re-exports them, which is where every caller reads them from.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from pantaray_llm.contracts.json_value import JSONValue


class LlmToolCall(BaseModel):
    model_config = ConfigDict(extra="forbid")

    call_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    arguments: dict[str, JSONValue]


class LlmToolResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    call_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    output: JSONValue


__all__ = ["LlmToolCall", "LlmToolResult"]
