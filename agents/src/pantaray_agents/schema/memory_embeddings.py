"""The Amazon Titan embedding contract.

The desktop runtime no longer uses this: it embeds locally, under the profile
its bundled model's manifest describes. These definitions stay because migration
0084 needs the profile the store was written with.

Pantaray Cloud の中継が配布済みのデスクトップへ見せる wire 契約は、Cloud 側の
`cloud_proxy/schema/memory_embeddings.py` が別に持つ。こちらとは共有しない。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

type MemoryEmbeddingProfileId = Literal[
    "memory.titan-text-v2-512.v1",
    "memory.titan-text-v2-1024.v1",
]
type MemorySearchSemanticStatus = Literal[
    "available",
    "not_ready",
    "provider_unavailable",
    "generation_changed",
    "contract_error",
]

MEMORY_EMBEDDING_PROFILE_ID: MemoryEmbeddingProfileId = "memory.titan-text-v2-512.v1"
MEMORY_EMBEDDING_PROFILE_1024_ID: MemoryEmbeddingProfileId = (
    "memory.titan-text-v2-1024.v1"
)
MEMORY_EMBEDDING_MODEL_ID = "amazon.titan-embed-text-v2:0"
MEMORY_EMBEDDING_DIMENSIONS = 512
MEMORY_EMBEDDING_NORMALIZED = True
MEMORY_EMBEDDING_MAX_DIMENSIONS = 1024
MEMORY_EMBEDDING_MAX_TEXTS = 1
MEMORY_EMBEDDING_MAX_IDENTIFIER_CHARS = 128
# Titan Text Embeddings V2 accepts 8,192 tokens. At the conservative bound of
# two tokens per character, 4,000 characters use at most 8,000 tokens and leave
# 192 tokens of headroom. The generation identity persists this chunking limit.
MEMORY_EMBEDDING_MAX_TEXT_CHARS = 4_000
MEMORY_SEARCH_SEMANTIC_STATUS_VALUES: tuple[MemorySearchSemanticStatus, ...] = (
    "available",
    "not_ready",
    "provider_unavailable",
    "generation_changed",
    "contract_error",
)


@dataclass(frozen=True, slots=True)
class MemoryEmbeddingProfile:
    profile_id: MemoryEmbeddingProfileId
    model_id: str
    dimensions: int
    normalized: bool


_MEMORY_EMBEDDING_PROFILES: dict[MemoryEmbeddingProfileId, MemoryEmbeddingProfile] = {
    MEMORY_EMBEDDING_PROFILE_ID: MemoryEmbeddingProfile(
        profile_id=MEMORY_EMBEDDING_PROFILE_ID,
        model_id=MEMORY_EMBEDDING_MODEL_ID,
        dimensions=MEMORY_EMBEDDING_DIMENSIONS,
        normalized=MEMORY_EMBEDDING_NORMALIZED,
    ),
    MEMORY_EMBEDDING_PROFILE_1024_ID: MemoryEmbeddingProfile(
        profile_id=MEMORY_EMBEDDING_PROFILE_1024_ID,
        model_id=MEMORY_EMBEDDING_MODEL_ID,
        dimensions=1024,
        normalized=MEMORY_EMBEDDING_NORMALIZED,
    ),
}


def resolve_memory_embedding_profile(
    profile_id: MemoryEmbeddingProfileId,
) -> MemoryEmbeddingProfile:
    return _MEMORY_EMBEDDING_PROFILES[profile_id]


type MemoryEmbeddingText = Annotated[
    str,
    StringConstraints(
        min_length=1,
        max_length=MEMORY_EMBEDDING_MAX_TEXT_CHARS,
        pattern=r"\S",
    ),
]
type MemoryEmbeddingVector = Annotated[
    list[float],
    Field(min_length=1, max_length=MEMORY_EMBEDDING_MAX_DIMENSIONS),
]


class MemoryEmbeddingRequestMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: str = Field(
        min_length=1,
        max_length=MEMORY_EMBEDDING_MAX_IDENTIFIER_CHARS,
        pattern=r"\S",
    )
    request_id: str = Field(
        min_length=1,
        max_length=MEMORY_EMBEDDING_MAX_IDENTIFIER_CHARS,
        pattern=r"\S",
    )


class MemoryEmbeddingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profile_id: MemoryEmbeddingProfileId
    texts: list[MemoryEmbeddingText] = Field(
        min_length=1,
        max_length=MEMORY_EMBEDDING_MAX_TEXTS,
    )
    metadata: MemoryEmbeddingRequestMetadata


class MemoryEmbeddingResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    profile_id: MemoryEmbeddingProfileId
    model_id: str = Field(min_length=1, pattern=r"\S")
    dimensions: int = Field(gt=0, le=MEMORY_EMBEDDING_MAX_DIMENSIONS)
    normalized: bool
    embeddings: list[MemoryEmbeddingVector] = Field(
        min_length=1,
        max_length=MEMORY_EMBEDDING_MAX_TEXTS,
    )

    @field_validator("embeddings", mode="before")
    @classmethod
    def reject_non_numeric_values(cls, value: object) -> object:
        if not isinstance(value, list):
            return value
        for vector in value:
            if not isinstance(vector, list):
                continue
            if any(
                isinstance(item, bool) or not isinstance(item, int | float)
                for item in vector
            ):
                raise ValueError("embedding vector must contain only numbers")
        return value

    @model_validator(mode="after")
    def validate_profile_and_vectors(self) -> MemoryEmbeddingResponse:
        profile = resolve_memory_embedding_profile(self.profile_id)
        if (
            self.model_id != profile.model_id
            or self.dimensions != profile.dimensions
            or self.normalized is not profile.normalized
        ):
            raise ValueError("embedding metadata does not match the selected profile")
        for vector in self.embeddings:
            if len(vector) != profile.dimensions:
                raise ValueError(
                    "embedding vector dimension does not match the profile"
                )
            if not all(math.isfinite(value) for value in vector):
                raise ValueError("embedding vector must contain only finite values")
            if not any(value != 0.0 for value in vector):
                raise ValueError("embedding vector must not be zero")
        return self


__all__ = [
    "MEMORY_EMBEDDING_DIMENSIONS",
    "MEMORY_EMBEDDING_MAX_DIMENSIONS",
    "MEMORY_EMBEDDING_MAX_IDENTIFIER_CHARS",
    "MEMORY_EMBEDDING_MAX_TEXTS",
    "MEMORY_EMBEDDING_MAX_TEXT_CHARS",
    "MEMORY_EMBEDDING_MODEL_ID",
    "MEMORY_EMBEDDING_NORMALIZED",
    "MEMORY_EMBEDDING_PROFILE_1024_ID",
    "MEMORY_EMBEDDING_PROFILE_ID",
    "MEMORY_SEARCH_SEMANTIC_STATUS_VALUES",
    "MemoryEmbeddingProfile",
    "MemoryEmbeddingProfileId",
    "MemoryEmbeddingRequest",
    "MemoryEmbeddingRequestMetadata",
    "MemoryEmbeddingResponse",
    "MemoryEmbeddingText",
    "MemoryEmbeddingVector",
    "MemorySearchSemanticStatus",
    "resolve_memory_embedding_profile",
]
