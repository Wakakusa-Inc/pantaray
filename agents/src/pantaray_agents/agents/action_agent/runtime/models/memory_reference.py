"""Strict references from initial memory summaries to managed artifacts."""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import PurePosixPath
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

type MemorySourceType = Literal["long_term_insight", "facts", "agent_experience"]

_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


def _non_blank(value: str) -> str:
    if not value.strip():
        raise ValueError("value must not be blank")
    return value


class MemoryArtifactFileReferenceModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    storage_path: str
    sha256: str
    byte_size: int = Field(ge=0)
    mime_type: str

    _validate_mime_type = field_validator("mime_type")(_non_blank)

    @field_validator("storage_path")
    @classmethod
    def validate_storage_path(cls, value: str) -> str:
        normalized = value.strip().replace("\\", "/")
        path = PurePosixPath(normalized)
        if not normalized or path.is_absolute():
            raise ValueError("storage_path must be a non-empty relative path")
        if any(part in {"", ".", ".."} for part in path.parts):
            raise ValueError("storage_path contains forbidden traversal")
        return str(path)

    @field_validator("sha256")
    @classmethod
    def validate_sha256(cls, value: str) -> str:
        if _SHA256_PATTERN.fullmatch(value) is None:
            raise ValueError("sha256 must be a lowercase hexadecimal digest")
        return value


class MemoryArtifactReferenceModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    source_type: MemorySourceType
    source_record_id: str
    artifact_id: str
    memory_key: str
    logical_updated_at: str
    files: tuple[MemoryArtifactFileReferenceModel, ...]

    _validate_source_record_id = field_validator("source_record_id")(_non_blank)
    _validate_artifact_id = field_validator("artifact_id")(_non_blank)

    @field_validator("files", mode="before")
    @classmethod
    def normalize_json_files(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value

    @field_validator("logical_updated_at")
    @classmethod
    def validate_timestamp(cls, value: str) -> str:
        try:
            datetime.fromisoformat(value)
        except ValueError as exc:
            raise ValueError(
                "logical_updated_at must be an ISO 8601 timestamp"
            ) from exc
        return value

    @model_validator(mode="after")
    def validate_reference(self) -> MemoryArtifactReferenceModel:
        if self.memory_key != f"memory_artifact:{self.artifact_id}":
            raise ValueError("memory_key must reference artifact_id")
        if not self.files:
            raise ValueError("files must not be empty")
        paths = tuple(file.storage_path for file in self.files)
        if len(paths) != len(set(paths)):
            raise ValueError("artifact file paths must be unique")
        return self


__all__ = [
    "MemoryArtifactFileReferenceModel",
    "MemoryArtifactReferenceModel",
    "MemorySourceType",
]
