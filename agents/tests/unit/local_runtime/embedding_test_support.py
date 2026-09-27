"""A stand-in embedding model for tests that need an index but not a real model.

The runtime reads every model-specific value from a manifest, so a test manifest
plus a model object that returns fixed vectors is enough to exercise indexing
and search without shipping model files into the test suite.
"""

from __future__ import annotations

from collections.abc import Sequence

from pantaray_agents.local_runtime.embedding_local import LocalEmbeddingManifest
from pantaray_agents.local_runtime.memory_catalog.embedding_generations import (
    current_embedding_specification,
)

EMBEDDING_DIMENSIONS = 512
EMBEDDING_MAX_TOKENS = 8_000
# The chunk length the catalog tests are written against. Production measures a
# much shorter one from the real tokenizer.
EMBEDDING_MAX_TEXT_CHARS = 4_000


def build_test_manifest(
    *,
    artifact_revision: str = "0123456789abcdef",
    model_slug: str = "test-embedding",
    dimensions: int = EMBEDDING_DIMENSIONS,
    max_text_chars: int = EMBEDDING_MAX_TEXT_CHARS,
) -> LocalEmbeddingManifest:
    return LocalEmbeddingManifest(
        model_id="pantaray/test-embedding",
        source_revision="0" * 40,
        model_slug=model_slug,
        artifact_revision=artifact_revision,
        model_file="model.onnx",
        model_sha256="0" * 64,
        tokenizer_file="tokenizer.json",
        tokenizer_sha256="1" * 64,
        dimensions=dimensions,
        max_tokens=EMBEDDING_MAX_TOKENS,
        max_text_chars=max_text_chars,
        pooling="mean",
        query_prefix="検索クエリ: ",
        document_prefix="検索文書: ",
    )


TEST_EMBEDDING_MANIFEST = build_test_manifest()
TEST_EMBEDDING_SPECIFICATION = current_embedding_specification(TEST_EMBEDDING_MANIFEST)


def unit_vector(dimensions: int = EMBEDDING_DIMENSIONS) -> tuple[float, ...]:
    return (1.0, *((0.0,) * (dimensions - 1)))


class StubEmbeddingModel:
    """Records what it embedded and returns the same unit vector every time."""

    def __init__(self, manifest: LocalEmbeddingManifest | None = None) -> None:
        self.manifest = manifest or TEST_EMBEDDING_MANIFEST
        self.documents: list[list[str]] = []
        self.queries: list[str] = []

    def embed_documents(self, texts: Sequence[str]) -> tuple[tuple[float, ...], ...]:
        self.documents.append(list(texts))
        return tuple(unit_vector(self.manifest.dimensions) for _ in texts)

    def embed_query(self, text: str) -> tuple[float, ...]:
        self.queries.append(text)
        return unit_vector(self.manifest.dimensions)


__all__ = [
    "EMBEDDING_DIMENSIONS",
    "EMBEDDING_MAX_TEXT_CHARS",
    "EMBEDDING_MAX_TOKENS",
    "TEST_EMBEDDING_MANIFEST",
    "TEST_EMBEDDING_SPECIFICATION",
    "StubEmbeddingModel",
    "build_test_manifest",
    "unit_vector",
]
