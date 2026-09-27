"""Typed image inputs shared by agents."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator


def _require_non_blank(value: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError("value must be a non-empty string")
    return normalized


class ImageInput(BaseModel):
    """User-supplied image stored in the user's local artifact scope."""

    model_config = ConfigDict(extra="forbid", strict=True)

    kind: Literal["image"] = "image"
    storage_path: str

    _validate_storage_path = field_validator("storage_path")(_require_non_blank)


__all__ = ["ImageInput"]
