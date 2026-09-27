"""The local embedding profile migration must not orphan projected rows.

These use the production migration list rather than `support.load_default_migrations`,
which stops below the reset version and would never reach this migration.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from pantaray_agents.local_runtime.memory_catalog.connection import (
    open_memory_catalog_connection,
)
from pantaray_agents.local_runtime.memory_catalog.domain_registration import (
    register_inline_domain_memory,
)
from pantaray_agents.local_runtime.memory_catalog.embedding_generations import (
    EmbeddingSpecification,
    activate_embedding_generation,
    ensure_user_embedding_generation,
)
from pantaray_agents.local_runtime.memory_catalog.semantic_index import (
    store_embedding_success,
)
from pantaray_agents.local_runtime.storage.migrations import (
    apply_migrations,
    verify_database_integrity,
)
from pantaray_agents.local_runtime.storage.migrations.specs import (
    load_default_migrations,
)
from pantaray_agents.local_runtime.storage.transactions import immediate_transaction

BUSY_TIMEOUT_MS = 5_000
MIGRATION_VERSION = 113
# What an installed store holds before this migration: a generation the previous
# model produced, under the profile id the old CHECK constraint allowed.
PREVIOUS_SPECIFICATION = EmbeddingSpecification(
    profile_id="memory.titan-text-v2-1024.v1",
    model_id="amazon.titan-embed-text-v2:0",
    dimensions=1024,
    normalized=True,
    max_text_chars=4_000,
)


def _store_with_projected_generation(tmp_path: Path) -> tuple[Path, int]:
    db_path = tmp_path / "runtime.db"
    apply_migrations(
        db_path=db_path,
        busy_timeout_ms=BUSY_TIMEOUT_MS,
        migrations=tuple(
            migration
            for migration in load_default_migrations()
            if migration.version < MIGRATION_VERSION
        ),
    )
    with open_memory_catalog_connection(
        db_path=db_path, busy_timeout_ms=BUSY_TIMEOUT_MS
    ) as connection:
        with immediate_transaction(connection):
            connection.execute(
                """
                INSERT INTO users(user_id, ui_language, created_at, updated_at)
                VALUES ('user-1', 'ja', '2026-01-01T00:00:00Z',
                        '2026-01-01T00:00:00Z')
                """
            )
            register_inline_domain_memory(
                connection=connection,
                user_id="user-1",
                source="fact",
                source_record_id="record-1",
                content="ある事実の記録。",
            )
    generation = ensure_user_embedding_generation(
        db_path=db_path,
        busy_timeout_ms=BUSY_TIMEOUT_MS,
        user_id="user-1",
        specification=PREVIOUS_SPECIFICATION,
    )
    with open_memory_catalog_connection(
        db_path=db_path, busy_timeout_ms=BUSY_TIMEOUT_MS
    ) as connection:
        with immediate_transaction(connection):
            rows = connection.execute(
                """
                SELECT work.fragment_id, work.chunk_index, fragments.content_sha256
                FROM memory_embedding_work AS work
                JOIN memory_fragments AS fragments
                  ON fragments.user_id = work.user_id
                 AND fragments.fragment_id = work.fragment_id
                WHERE work.generation_id = ?
                """,
                (generation.generation_id,),
            ).fetchall()
            assert rows
            for row in rows:
                store_embedding_success(
                    connection,
                    user_id="user-1",
                    generation_id=generation.generation_id,
                    fragment_id=str(row[0]),
                    chunk_index=int(row[1]),
                    fragment_content_sha256=str(row[2]),
                    vector=[1.0, *([0.0] * 1_023)],
                    created_at="2026-01-01T00:00:00Z",
                )
    activate_embedding_generation(
        db_path=db_path,
        busy_timeout_ms=BUSY_TIMEOUT_MS,
        user_id="user-1",
        generation_id=generation.generation_id,
    )
    return db_path, generation.generation_id


def test_migration_keeps_an_existing_generation_referentially_intact(
    tmp_path: Path,
) -> None:
    db_path, generation_id = _store_with_projected_generation(tmp_path)

    apply_migrations(
        db_path=db_path,
        busy_timeout_ms=BUSY_TIMEOUT_MS,
        migrations=load_default_migrations(),
    )

    # A violation here is unrecoverable in the field: the schema version has
    # already advanced, so the migration never runs again and every later start
    # fails on the same check.
    verify_database_integrity(db_path=db_path, busy_timeout_ms=BUSY_TIMEOUT_MS)
    with sqlite3.connect(db_path) as connection:
        projected = connection.execute(
            f"SELECT COUNT(*) FROM memory_embedding_entries_g{generation_id}"
        ).fetchone()[0]
        scopes = connection.execute(
            "SELECT COUNT(*) FROM memory_embedding_user_generations"
        ).fetchone()[0]
    assert projected == 1
    assert scopes == 1


def test_migration_lets_a_local_profile_id_be_stored(tmp_path: Path) -> None:
    db_path, _ = _store_with_projected_generation(tmp_path)
    apply_migrations(
        db_path=db_path,
        busy_timeout_ms=BUSY_TIMEOUT_MS,
        migrations=load_default_migrations(),
    )

    local = EmbeddingSpecification(
        profile_id="memory.local.test-embedding.256.0123456789abcdef",
        model_id="pantaray/test-embedding",
        dimensions=256,
        normalized=True,
        max_text_chars=256,
    )
    building = ensure_user_embedding_generation(
        db_path=db_path,
        busy_timeout_ms=BUSY_TIMEOUT_MS,
        user_id="user-1",
        specification=local,
    )

    assert building.specification == local
    verify_database_integrity(db_path=db_path, busy_timeout_ms=BUSY_TIMEOUT_MS)


def test_migration_versions_are_unique_and_ordered() -> None:
    """Two branches adding the same number would apply only one of them."""
    versions = [migration.version for migration in load_default_migrations()]

    assert versions == sorted(versions)
    assert len(versions) == len(set(versions))
    assert MIGRATION_VERSION in versions
