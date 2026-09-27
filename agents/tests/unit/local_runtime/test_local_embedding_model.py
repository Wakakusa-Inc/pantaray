from __future__ import annotations

import json
import os
from collections.abc import Iterator
from pathlib import Path

import numpy
import pytest

from pantaray_agents.local_runtime.embedding_local import (
    LOCAL_EMBEDDING_MANIFEST_FILENAME,
    LOCAL_EMBEDDING_MODEL_DIR_ENV,
    WORST_CASE_CHUNK_UNIT,
    LocalEmbeddingUnavailableError,
    artifact_revision_digest,
    file_sha256,
    load_local_embedding_model,
    load_verified_manifest,
    pool_hidden_states,
    require_chunk_fits_window,
    reset_local_embedding_model_cache,
    worst_case_chunk_text,
)
from pantaray_agents.local_runtime.memory_catalog.embedding_chunks import (
    split_memory_embedding_chunks,
)
from pantaray_agents.local_runtime.memory_catalog.embedding_generations import (
    current_embedding_specification,
)

MODEL_BYTES = b"not a real graph"
TOKENIZER_BYTES = b"not a real tokenizer"


def _write_model_dir(tmp_path: Path, **overrides: object) -> Path:
    model_dir = tmp_path / "embedding_model"
    model_dir.mkdir()
    (model_dir / "model.onnx").write_bytes(MODEL_BYTES)
    (model_dir / "tokenizer.json").write_bytes(TOKENIZER_BYTES)
    identity: dict[str, object] = {
        "model_id": "pantaray/test-embedding",
        "source_revision": "0" * 40,
        "model_slug": "test-embedding",
        "model_file": "model.onnx",
        "model_sha256": file_sha256(model_dir / "model.onnx"),
        "tokenizer_file": "tokenizer.json",
        "tokenizer_sha256": file_sha256(model_dir / "tokenizer.json"),
        "dimensions": 256,
        "max_tokens": 512,
        "max_text_chars": 400,
        "pooling": "mean",
        "query_prefix": "検索クエリ: ",
        "document_prefix": "検索文書: ",
    }
    document = {
        **identity,
        "artifact_revision": artifact_revision_digest(**identity),  # type: ignore[arg-type]
        **overrides,
    }
    (model_dir / LOCAL_EMBEDDING_MANIFEST_FILENAME).write_text(
        json.dumps(document, ensure_ascii=False), "utf-8"
    )
    return model_dir


def test_manifest_builds_the_profile_id_and_chunk_length(tmp_path: Path) -> None:
    manifest = load_verified_manifest(_write_model_dir(tmp_path))

    assert manifest.profile_id == (
        f"memory.local.test-embedding.256.{manifest.artifact_revision}"
    )
    assert manifest.max_text_chars == 400
    assert current_embedding_specification(manifest).normalized is True


def test_worst_case_chunk_text_is_exactly_the_chunk_length() -> None:
    for length in (1, len(WORST_CASE_CHUNK_UNIT), 400, 4_001):
        assert len(worst_case_chunk_text(length)) == length


def test_a_chunk_that_overflows_the_window_is_refused(tmp_path: Path) -> None:
    manifest = load_verified_manifest(_write_model_dir(tmp_path))

    require_chunk_fits_window(token_count=manifest.max_tokens, manifest=manifest)
    # Past the window the tokenizer truncates, and the tail of the chunk would
    # never reach the index while nothing reported it.
    with pytest.raises(LocalEmbeddingUnavailableError, match="past the window"):
        require_chunk_fits_window(
            token_count=manifest.max_tokens + 1, manifest=manifest
        )


def test_manifest_rejects_a_model_file_that_was_replaced(tmp_path: Path) -> None:
    model_dir = _write_model_dir(tmp_path)
    (model_dir / "model.onnx").write_bytes(MODEL_BYTES + b"!")

    with pytest.raises(LocalEmbeddingUnavailableError, match="manifest digest"):
        load_verified_manifest(model_dir)


def test_manifest_rejects_preprocessing_edited_without_a_new_revision(
    tmp_path: Path,
) -> None:
    model_dir = _write_model_dir(tmp_path, query_prefix="something else: ")

    with pytest.raises(LocalEmbeddingUnavailableError, match="revision"):
        load_verified_manifest(model_dir)


def test_missing_model_directory_is_unavailable_rather_than_fatal(
    tmp_path: Path,
) -> None:
    with pytest.raises(LocalEmbeddingUnavailableError, match="unreadable"):
        load_verified_manifest(tmp_path / "absent")


def test_unset_model_directory_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(LOCAL_EMBEDDING_MODEL_DIR_ENV, raising=False)
    reset_local_embedding_model_cache()
    try:
        with pytest.raises(
            LocalEmbeddingUnavailableError, match=LOCAL_EMBEDDING_MODEL_DIR_ENV
        ):
            load_local_embedding_model()
    finally:
        reset_local_embedding_model_cache()


def test_unreadable_graph_is_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(LOCAL_EMBEDDING_MODEL_DIR_ENV, str(_write_model_dir(tmp_path)))
    reset_local_embedding_model_cache()
    try:
        with pytest.raises(LocalEmbeddingUnavailableError, match="could not be loaded"):
            load_local_embedding_model()
    finally:
        reset_local_embedding_model_cache()


def test_mean_pooling_ignores_padding_and_returns_unit_vectors() -> None:
    hidden_states = numpy.asarray(
        [[[3.0, 4.0], [3.0, 4.0], [100.0, -100.0]]], dtype=numpy.float32
    )
    attention_mask = numpy.asarray([[1, 1, 0]], dtype=numpy.int64)

    pooled = pool_hidden_states(hidden_states, attention_mask, pooling="mean")

    assert pooled == pytest.approx(numpy.asarray([[0.6, 0.8]], dtype=numpy.float32))


def test_cls_pooling_takes_the_first_token() -> None:
    hidden_states = numpy.asarray([[[0.0, 5.0], [9.0, 9.0]]], dtype=numpy.float32)
    attention_mask = numpy.asarray([[1, 1]], dtype=numpy.int64)

    pooled = pool_hidden_states(hidden_states, attention_mask, pooling="cls")

    assert pooled == pytest.approx(numpy.asarray([[0.0, 1.0]], dtype=numpy.float32))


def test_pooling_refuses_a_vector_with_no_direction() -> None:
    # Dividing by a clipped floor would turn this into an arbitrary direction
    # that the index would store as if it meant something.
    with pytest.raises(LocalEmbeddingUnavailableError, match="no direction"):
        pool_hidden_states(
            numpy.zeros((1, 2, 4), dtype=numpy.float32),
            numpy.ones((1, 2), dtype=numpy.int64),
            pooling="mean",
        )


def test_pooling_refuses_a_graph_that_does_not_emit_token_states() -> None:
    with pytest.raises(LocalEmbeddingUnavailableError, match="per-token"):
        pool_hidden_states(
            numpy.zeros((1, 2), dtype=numpy.float32),
            numpy.ones((1, 2), dtype=numpy.int64),
            pooling="mean",
        )


# The bundled model is not committed. `scripts/dev/prepare_embedding_model.py`
# writes it and prints the directory to point this at.
@pytest.fixture
def installed_model() -> Iterator[object]:
    if not os.getenv(LOCAL_EMBEDDING_MODEL_DIR_ENV):
        pytest.skip(f"{LOCAL_EMBEDDING_MODEL_DIR_ENV} is not set")
    reset_local_embedding_model_cache()
    try:
        yield load_local_embedding_model()
    finally:
        reset_local_embedding_model_cache()


def test_installed_model_keeps_a_full_chunk_inside_its_token_window(
    installed_model,
) -> None:
    manifest = installed_model.manifest
    chunk = split_memory_embedding_chunks(
        worst_case_chunk_text(manifest.max_text_chars * 3),
        max_text_chars=manifest.max_text_chars,
    )[0]
    tokenizer = installed_model._tokenizer  # noqa: SLF001

    assert len(chunk.content_text) == manifest.max_text_chars
    for text in (
        manifest.document_prefix + chunk.content_text,
        manifest.query_prefix + chunk.content_text,
    ):
        assert len(tokenizer.encode(text).ids) <= manifest.max_tokens


def test_installed_model_ranks_related_memories_above_unrelated_ones(
    installed_model,
) -> None:
    documents = (
        "認証トークンの失効後は再ログインが必要になる。",
        "The release workflow uploads the signed build to GitHub Releases.",
        "昼食はラーメンにした。",
    )
    vectors = installed_model.embed_documents(documents)
    queries = {
        "ログインのやり直しが必要になる条件": 0,
        "where does the signed build get published": 1,
    }

    for query, expected in queries.items():
        query_vector = installed_model.embed_query(query)
        scores = [
            sum(a * b for a, b in zip(query_vector, vector, strict=True))
            for vector in vectors
        ]
        assert scores.index(max(scores)) == expected

    for vector in vectors:
        assert sum(value * value for value in vector) == pytest.approx(1.0, abs=1e-5)
