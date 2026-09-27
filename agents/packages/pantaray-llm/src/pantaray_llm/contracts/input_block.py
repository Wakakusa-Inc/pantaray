"""Typed blocks a caller can place in one model input.

These sit below both ``request`` and ``conversation``: a request's ``messages``
and an Action conversation's user items and tool-result attachments describe the
same thing -- text or an image handed to the model -- so the blocks own their
own module and neither contract imports the other. ``request`` re-exports them,
which is where every caller reads them from.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from pantaray_llm.contracts.media import LlmMediaDescriptor


class LlmImageDescriptor(LlmMediaDescriptor):
    pass


class LlmInputTextBlock(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["input_text"]
    text: str = Field(min_length=1)


class LlmInputImageBlock(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["input_image"]
    image: LlmImageDescriptor


type LlmInputBlock = LlmInputTextBlock | LlmInputImageBlock


__all__ = [
    "LlmImageDescriptor",
    "LlmInputBlock",
    "LlmInputImageBlock",
    "LlmInputTextBlock",
]
