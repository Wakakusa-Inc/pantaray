from __future__ import annotations

from pathlib import Path

import pytest

from pantaray_agents.local_runtime.memory_catalog.connection import (
    open_memory_catalog_connection,
)
from pantaray_agents.local_runtime.memory_catalog.domain_registration import (
    register_inline_domain_memory,
)
from pantaray_agents.local_runtime.memory_catalog.embedding_chunks import (
    split_memory_embedding_chunks,
)
from pantaray_agents.local_runtime.memory_catalog.embedding_generations import (
    EmbeddingSpecification,
    MemoryEmbeddingActivationError,
    activate_embedding_generation,
    current_embedding_specification,
    delete_user_embedding_generations_in_transaction,
    ensure_user_embedding_generation,
    start_embedding_reprojection,
)
from pantaray_agents.local_runtime.memory_catalog.semantic_index import (
    store_embedding_success,
)
from pantaray_agents.local_runtime.storage.migrations import (
    load_default_migrations,
)
from pantaray_agents.local_runtime.storage.transactions import immediate_transaction

from .embedding_test_support import (
    TEST_EMBEDDING_SPECIFICATION,
    build_test_manifest,
    unit_vector,
)
from .migrated_db import prepare_test_database

BUSY_TIMEOUT_MS = 1_000
LEGACY_EMBEDDING_MAX_TEXT_CHARS = 50_000
MAX_TEXT_CHARS = TEST_EMBEDDING_SPECIFICATION.max_text_chars


def _alternate_specification() -> EmbeddingSpecification:
    """What a different bundled artifact would index at."""
    return current_embedding_specification(
        build_test_manifest(artifact_revision="fedcba9876543210", dimensions=1024)
    )


def _database_with_user(tmp_path: Path) -> Path:
    db_path = tmp_path / "runtime.db"
    prepare_test_database(
        db_path=db_path,
        busy_timeout_ms=BUSY_TIMEOUT_MS,
        migrations=load_default_migrations(),
    )
    with open_memory_catalog_connection(
        db_path=db_path, busy_timeout_ms=BUSY_TIMEOUT_MS
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
    return db_path


def _activate_empty_current_generation(db_path: Path) -> int:
    generation = ensure_user_embedding_generation(
        db_path=db_path,
        busy_timeout_ms=BUSY_TIMEOUT_MS,
        user_id="user-1",
        specification=TEST_EMBEDDING_SPECIFICATION,
    )
    activate_embedding_generation(
        db_path=db_path,
        busy_timeout_ms=BUSY_TIMEOUT_MS,
        user_id="user-1",
        generation_id=generation.generation_id,
        activated_at="2026-08-09T00:00:00Z",
    )
    return generation.generation_id


def test_japanese_content_over_limit_is_split_into_multiple_chunks() -> None:
    content = "記" * (MAX_TEXT_CHARS + 1)

    chunks = split_memory_embedding_chunks(content, max_text_chars=MAX_TEXT_CHARS)

    assert [len(chunk.content_text) for chunk in chunks] == [
        MAX_TEXT_CHARS,
        1,
    ]


def test_chunking_parameter_change_creates_new_generation(tmp_path: Path) -> None:
    db_path = _database_with_user(tmp_path)
    legacy_generation = ensure_user_embedding_generation(
        db_path=db_path,
        busy_timeout_ms=BUSY_TIMEOUT_MS,
        user_id="user-1",
        specification=EmbeddingSpecification(
            model_id=TEST_EMBEDDING_SPECIFICATION.model_id,
            dimensions=TEST_EMBEDDING_SPECIFICATION.dimensions,
            normalized=TEST_EMBEDDING_SPECIFICATION.normalized,
            max_text_chars=LEGACY_EMBEDDING_MAX_TEXT_CHARS,
            profile_id=TEST_EMBEDDING_SPECIFICATION.profile_id,
        ),
    )
    activate_embedding_generation(
        db_path=db_path,
        busy_timeout_ms=BUSY_TIMEOUT_MS,
        user_id="user-1",
        generation_id=legacy_generation.generation_id,
    )

    current_generation = ensure_user_embedding_generation(
        db_path=db_path,
        busy_timeout_ms=BUSY_TIMEOUT_MS,
        user_id="user-1",
        specification=TEST_EMBEDDING_SPECIFICATION,
    )
    with open_memory_catalog_connection(
        db_path=db_path, busy_timeout_ms=BUSY_TIMEOUT_MS
    ) as connection:
        with immediate_transaction(connection):
            register_inline_domain_memory(
                connection=connection,
                user_id="user-1",
                source="fact",
                source_record_id="chunk-identity",
                content="記" * (MAX_TEXT_CHARS + 1),
            )
        work_counts = connection.execute(
            """
            SELECT generation_id, COUNT(*)
            FROM memory_embedding_work
            GROUP BY generation_id
            ORDER BY generation_id
            """
        ).fetchall()

    assert current_generation.generation_id != legacy_generation.generation_id
    assert current_generation.specification.max_text_chars == MAX_TEXT_CHARS
    assert [tuple(row) for row in work_counts] == [
        (legacy_generation.generation_id, 1),
        (current_generation.generation_id, 2),
    ]


def test_different_dimension_generations_coexist(tmp_path: Path) -> None:
    db_path = _database_with_user(tmp_path)
    active_generation_id = _activate_empty_current_generation(db_path)

    building = start_embedding_reprojection(
        db_path=db_path,
        busy_timeout_ms=BUSY_TIMEOUT_MS,
        user_id="user-1",
        specification=_alternate_specification(),
    )

    with open_memory_catalog_connection(
        db_path=db_path, busy_timeout_ms=BUSY_TIMEOUT_MS
    ) as connection:
        scopes = connection.execute(
            """
            SELECT generation_id, state
            FROM memory_embedding_user_generations
            WHERE user_id = 'user-1'
            ORDER BY generation_id
            """
        ).fetchall()
        table_sql = connection.execute(
            "SELECT sql FROM sqlite_master WHERE name = ?",
            (f"memory_embedding_vectors_g{building.generation_id}",),
        ).fetchone()

    assert [tuple(row) for row in scopes] == [
        (active_generation_id, "active"),
        (building.generation_id, "building"),
    ]
    assert table_sql is not None and "FLOAT[1024]" in str(table_sql[0])


def test_same_spec_reprojection_keeps_active_until_atomic_activation(
    tmp_path: Path,
) -> None:
    db_path = _database_with_user(tmp_path)
    old_generation_id = _activate_empty_current_generation(db_path)
    building = start_embedding_reprojection(
        db_path=db_path,
        busy_timeout_ms=BUSY_TIMEOUT_MS,
        user_id="user-1",
        specification=TEST_EMBEDDING_SPECIFICATION,
    )

    with open_memory_catalog_connection(
        db_path=db_path, busy_timeout_ms=BUSY_TIMEOUT_MS
    ) as connection:
        active_before = connection.execute(
            """
            SELECT generation_id FROM memory_embedding_user_generations
            WHERE user_id = 'user-1' AND state = 'active'
            """
        ).fetchone()
    assert active_before is not None
    assert tuple(active_before) == (old_generation_id,)

    activate_embedding_generation(
        db_path=db_path,
        busy_timeout_ms=BUSY_TIMEOUT_MS,
        user_id="user-1",
        generation_id=building.generation_id,
    )

    with open_memory_catalog_connection(
        db_path=db_path, busy_timeout_ms=BUSY_TIMEOUT_MS
    ) as connection:
        scopes = connection.execute(
            """
            SELECT generation_id, state
            FROM memory_embedding_user_generations
            WHERE user_id = 'user-1'
            ORDER BY generation_id
            """
        ).fetchall()
        old_table = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE name = ?",
            (f"memory_embedding_vectors_g{old_generation_id}",),
        ).fetchone()
    assert [tuple(row) for row in scopes] == [(building.generation_id, "active")]
    assert old_table is None


def test_ensure_profile_change_preserves_active_until_atomic_activation(
    tmp_path: Path,
) -> None:
    db_path = _database_with_user(tmp_path)
    old_generation_id = _activate_empty_current_generation(db_path)
    desired = _alternate_specification()

    building = ensure_user_embedding_generation(
        db_path=db_path,
        busy_timeout_ms=BUSY_TIMEOUT_MS,
        user_id="user-1",
        specification=desired,
    )

    with open_memory_catalog_connection(
        db_path=db_path, busy_timeout_ms=BUSY_TIMEOUT_MS
    ) as connection:
        scopes = connection.execute(
            """
            SELECT generation_id, state
            FROM memory_embedding_user_generations
            WHERE user_id = 'user-1'
            """
        ).fetchall()
    assert building.specification == desired
    assert [tuple(row) for row in scopes] == [
        (old_generation_id, "active"),
        (building.generation_id, "building"),
    ]

    activate_embedding_generation(
        db_path=db_path,
        busy_timeout_ms=BUSY_TIMEOUT_MS,
        user_id="user-1",
        generation_id=building.generation_id,
    )
    with open_memory_catalog_connection(
        db_path=db_path, busy_timeout_ms=BUSY_TIMEOUT_MS
    ) as connection:
        activated = connection.execute(
            """
            SELECT generation_id, state
            FROM memory_embedding_user_generations
            WHERE user_id = 'user-1'
            """
        ).fetchall()
        old_table = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE name = ?",
            (f"memory_embedding_vectors_g{old_generation_id}",),
        ).fetchone()
    assert [tuple(row) for row in activated] == [(building.generation_id, "active")]
    assert old_table is None


def test_activation_rejects_missing_fragment_embedding(tmp_path: Path) -> None:
    db_path = _database_with_user(tmp_path)
    generation = ensure_user_embedding_generation(
        db_path=db_path,
        busy_timeout_ms=BUSY_TIMEOUT_MS,
        user_id="user-1",
        specification=TEST_EMBEDDING_SPECIFICATION,
    )
    with open_memory_catalog_connection(
        db_path=db_path, busy_timeout_ms=BUSY_TIMEOUT_MS
    ) as connection:
        with immediate_transaction(connection):
            register_inline_domain_memory(
                connection=connection,
                user_id="user-1",
                source="fact",
                source_record_id="fact-1",
                content="Unprojected durable fact.",
            )

    with pytest.raises(
        MemoryEmbeddingActivationError,
        match="incomplete or inconsistent",
    ):
        activate_embedding_generation(
            db_path=db_path,
            busy_timeout_ms=BUSY_TIMEOUT_MS,
            user_id="user-1",
            generation_id=generation.generation_id,
        )


def test_activation_requires_every_semantic_chunk(tmp_path: Path) -> None:
    db_path = _database_with_user(tmp_path)
    generation = ensure_user_embedding_generation(
        db_path=db_path,
        busy_timeout_ms=BUSY_TIMEOUT_MS,
        user_id="user-1",
        specification=TEST_EMBEDDING_SPECIFICATION,
    )
    with open_memory_catalog_connection(
        db_path=db_path, busy_timeout_ms=BUSY_TIMEOUT_MS
    ) as connection:
        with immediate_transaction(connection):
            register_inline_domain_memory(
                connection=connection,
                user_id="user-1",
                source="fact",
                source_record_id="fact-long",
                content="x" * (MAX_TEXT_CHARS + 1),
            )
            work = connection.execute(
                """
                SELECT work.fragment_id, work.chunk_index,
                       fragments.content_sha256
                FROM memory_embedding_work AS work
                JOIN memory_fragments AS fragments
                  ON fragments.user_id = work.user_id
                 AND fragments.fragment_id = work.fragment_id
                ORDER BY work.chunk_index
                """
            ).fetchall()
            assert [int(row[1]) for row in work] == [0, 1]
            store_embedding_success(
                connection,
                user_id="user-1",
                generation_id=generation.generation_id,
                fragment_id=str(work[0][0]),
                chunk_index=0,
                fragment_content_sha256=str(work[0][2]),
                vector=unit_vector(),
                created_at="2026-08-09T00:00:00Z",
            )
            connection.execute(
                """
                DELETE FROM memory_embedding_work
                WHERE user_id = 'user-1' AND chunk_index = 1
                """
            )

    with pytest.raises(
        MemoryEmbeddingActivationError,
        match="incomplete or inconsistent",
    ):
        activate_embedding_generation(
            db_path=db_path,
            busy_timeout_ms=BUSY_TIMEOUT_MS,
            user_id="user-1",
            generation_id=generation.generation_id,
        )


def test_user_generation_deletion_removes_unused_dynamic_tables(
    tmp_path: Path,
) -> None:
    db_path = _database_with_user(tmp_path)
    generation_id = _activate_empty_current_generation(db_path)
    with open_memory_catalog_connection(
        db_path=db_path, busy_timeout_ms=BUSY_TIMEOUT_MS
    ) as connection:
        with immediate_transaction(connection):
            delete_user_embedding_generations_in_transaction(
                connection,
                user_id="user-1",
            )
        remaining = connection.execute(
            """
            SELECT name FROM sqlite_master
            WHERE name IN (
                'memory_embedding_generations',
                ?,
                ?
            )
            ORDER BY name
            """,
            (
                f"memory_embedding_entries_g{generation_id}",
                f"memory_embedding_vectors_g{generation_id}",
            ),
        ).fetchall()
        generation_count = connection.execute(
            "SELECT COUNT(*) FROM memory_embedding_generations"
        ).fetchone()[0]

    assert [str(row[0]) for row in remaining] == ["memory_embedding_generations"]
    assert generation_count == 0
