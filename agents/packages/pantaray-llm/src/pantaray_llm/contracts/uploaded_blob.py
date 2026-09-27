from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class UploadedBlob:
    field_name: str
    payload: bytes
    mime_type: str


__all__ = ["UploadedBlob"]
