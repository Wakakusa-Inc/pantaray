from __future__ import annotations

import math
from pathlib import Path

import pytest

from pantaray_agents.local_runtime.memory_catalog.connection import (
    open_memory_catalog_connection,
)
from pantaray_agents.local_runtime.memory_catalog.domain_registration import (
    register_inline_domain_memory,
)
from pantaray_agents.local_runtime.memory_catalog.embedding_chunks import (
    memory_embedding_chunk_at,
)
from pantaray_agents.local_runtime.memory_catalog.embedding_generations import (
    ensure_user_embedding_generation,
)
from pantaray_agents.local_runtime.memory_catalog.semantic_index import (
    MemoryEmbeddingValidationError,
    decode_embedding,
    encode_embedding,
    store_embedding_success,
)
from pantaray_agents.local_runtime.storage.migrations import (
    load_default_migrations,
)
from pantaray_agents.local_runtime.storage.transactions import immediate_transaction

from .embedding_test_support import (
    EMBEDDING_DIMENSIONS,
    TEST_EMBEDDING_SPECIFICATION,
    unit_vector,
)
from .migrated_db import prepare_test_database

MAX_TEXT_CHARS = TEST_EMBEDDING_SPECIFICATION.max_text_chars


def _create_pending_fragment(db_path: Path) -> tuple[str, str, int]:
    prepare_test_database(
        db_path=db_path,
        busy_timeout_ms=1_000,
        migrations=load_default_migrations(),
    )
    with open_memory_catalog_connection(
        db_path=db_path,
        busy_timeout_ms=1_000,
    ) as connection:
        with immediate_transaction(connection):
            connection.execute(
                """
                INSERT INTO users(user_id, ui_language, created_at, updated_at)
                VALUES (
                    'user-1', 'ja',
                    '2026-08-09T00:00:00Z', '2026-08-09T00:00:00Z'
                )
                """
            )
            register_inline_domain_memory(
                connection=connection,
                user_id="user-1",
                source="activity_log",
                source_record_id="activity-1",
                content="Remember the deployment verification result.",
            )
    generation = ensure_user_embedding_generation(
        db_path=db_path,
        busy_timeout_ms=1_000,
        user_id="user-1",
        specification=TEST_EMBEDDING_SPECIFICATION,
    )
    with open_memory_catalog_connection(
        db_path=db_path,
        busy_timeout_ms=1_000,
    ) as connection:
        row = connection.execute(
            """
            SELECT fragments.fragment_id, fragments.content_sha256
            FROM memory_fragments AS fragments
            JOIN memory_embedding_work AS work
              ON work.user_id = fragments.user_id
             AND work.fragment_id = fragments.fragment_id
            WHERE fragments.user_id = 'user-1'
            """
        ).fetchone()
    assert row is not None
    return str(row[0]), str(row[1]), generation.generation_id


def test_embedding_codec_is_fixed_little_endian_float32() -> None:
    encoded = encode_embedding(unit_vector(), dimensions=EMBEDDING_DIMENSIONS)

    assert len(encoded) == EMBEDDING_DIMENSIONS * 4
    assert decode_embedding(encoded, dimensions=EMBEDDING_DIMENSIONS) == unit_vector()


@pytest.mark.parametrize(
    "vector",
    [
        [0.0] * EMBEDDING_DIMENSIONS,
        [math.nan, *([0.0] * (EMBEDDING_DIMENSIONS - 1))],
        [1.0],
    ],
)
def test_embedding_codec_rejects_invalid_vectors(vector: list[float]) -> None:
    with pytest.raises(MemoryEmbeddingValidationError):
        encode_embedding(vector, dimensions=EMBEDDING_DIMENSIONS)


def test_store_embedding_writes_manifest_and_vector_atomically(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "runtime.db"
    fragment_id, content_sha256, generation_id = _create_pending_fragment(db_path)

    with open_memory_catalog_connection(
        db_path=db_path,
        busy_timeout_ms=1_000,
    ) as connection:
        with immediate_transaction(connection):
            store_embedding_success(
                connection,
                user_id="user-1",
                generation_id=generation_id,
                fragment_id=fragment_id,
                chunk_index=0,
                fragment_content_sha256=content_sha256,
                vector=list(unit_vector()),
                created_at="2026-08-09T00:00:00Z",
            )
        manifest = connection.execute(
            f"""
            SELECT fragment_id, chunk_index, fragment_content_sha256,
                   chunk_content_sha256
            FROM memory_embedding_entries_g{generation_id}
            """
        ).fetchone()
        vector_count = connection.execute(
            f"SELECT COUNT(*) FROM memory_embedding_vectors_g{generation_id}"
        ).fetchone()[0]
        pending_count = connection.execute(
            "SELECT COUNT(*) FROM memory_embedding_work"
        ).fetchone()[0]

    assert manifest is not None
    chunk = memory_embedding_chunk_at(
        "Remember the deployment verification result.",
        chunk_index=0,
        max_text_chars=MAX_TEXT_CHARS,
    )
    assert tuple(manifest) == (fragment_id, 0, content_sha256, chunk.content_sha256)
    assert vector_count == 1
    assert pending_count == 0
