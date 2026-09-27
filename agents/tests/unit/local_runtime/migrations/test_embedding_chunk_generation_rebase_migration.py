from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from pantaray_agents.local_runtime.memory_catalog.embedding_chunks import (
    split_memory_embedding_chunks,
)
from pantaray_agents.local_runtime.memory_catalog.embedding_generation_storage import (
    create_embedding_generation_storage,
)
from pantaray_agents.local_runtime.memory_catalog.embedding_generations import (
    activate_embedding_generation_in_transaction,
)
from pantaray_agents.local_runtime.memory_catalog.fragments import content_sha256
from pantaray_agents.local_runtime.storage.migrations import MigrationError
from pantaray_agents.local_runtime.storage.migrations import (
    embedding_chunk_generation_rebase as rebase_migration,
)
from pantaray_agents.local_runtime.storage.transactions import immediate_transaction
from pantaray_agents.schema.memory_embeddings import (
    MEMORY_EMBEDDING_MAX_TEXT_CHARS,
    MEMORY_EMBEDDING_MODEL_ID,
    MEMORY_EMBEDDING_PROFILE_1024_ID,
)

from .support import (
    _configure_connection,
    _insert_user,
    _migrations_before,
    _migrations_through,
    apply_migrations,
    load_default_migrations,
)

BUSY_TIMEOUT_MS = 1_000
MIGRATION_0071 = "0071_memory_semantic_index.sql"
MIGRATION_0083 = "0083_embedding_chunk_generation_identity.sql"
MIGRATION_0084 = "0084_embedding_chunk_generation_rebase.sql"
TIMESTAMP = "2026-08-24T00:00:00Z"
CONTENT = "記" * 60_000
CONTENT_SHA256 = content_sha256(CONTENT)


def _create_database_before_v71(tmp_path: Path, *, users: tuple[str, ...]) -> Path:
    db_path = tmp_path / "runtime.db"
    migrations = load_default_migrations()
    apply_migrations(
        db_path=db_path,
        busy_timeout_ms=BUSY_TIMEOUT_MS,
        migrations=_migrations_before(migrations, MIGRATION_0071),
    )
    with sqlite3.connect(db_path) as connection:
        _configure_connection(connection, BUSY_TIMEOUT_MS)
        with connection:
            for index, user_id in enumerate(users):
                _insert_user(connection, user_id)
                connection.execute(
                    """
                    INSERT INTO memory_nodes(
                        user_id, node_id, source_type, source_record_id,
                        lifecycle, integrity, current_revision_id,
                        created_at, updated_at
                    ) VALUES (?, ?, 'fact', ?, 'preparing', 'healthy', NULL, ?, ?)
                    """,
                    (
                        user_id,
                        f"node-{index}",
                        f"fact-{index}",
                        TIMESTAMP,
                        TIMESTAMP,
                    ),
                )
                connection.execute(
                    """
                    INSERT INTO memory_revisions(
                        user_id, revision_id, node_id, body_kind, inline_body,
                        artifact_root_path, fragment_schema_version,
                        content_sha256, created_at, profile_brief
                    ) VALUES (?, ?, ?, 'inline', ?, NULL, 1, ?, ?, NULL)
                    """,
                    (
                        user_id,
                        f"revision-{index}",
                        f"node-{index}",
                        CONTENT,
                        CONTENT_SHA256,
                        TIMESTAMP,
                    ),
                )
                connection.execute(
                    """
                    UPDATE memory_nodes
                    SET lifecycle = 'active', current_revision_id = ?
                    WHERE user_id = ? AND node_id = ?
                    """,
                    (f"revision-{index}", user_id, f"node-{index}"),
                )
                connection.execute(
                    """
                    INSERT INTO memory_fragments(
                        user_id, fragment_id, revision_id, source_path,
                        block_kind, block_index, heading_path, content_text,
                        content_sha256
                    ) VALUES (?, ?, ?, 'memory.md', 'paragraph', 0, NULL, ?, ?)
                    """,
                    (
                        user_id,
                        f"fragment-{index}",
                        f"revision-{index}",
                        CONTENT,
                        CONTENT_SHA256,
                    ),
                )
    return db_path


def _apply_through(db_path: Path, migration_name: str) -> None:
    apply_migrations(
        db_path=db_path,
        busy_timeout_ms=BUSY_TIMEOUT_MS,
        migrations=_migrations_through(load_default_migrations(), migration_name),
    )


def test_v84_rebases_v71_building_generation_and_trigger_work(
    tmp_path: Path,
) -> None:
    db_path = _create_database_before_v71(tmp_path, users=("user-1",))
    _apply_through(db_path, MIGRATION_0083)
    with sqlite3.connect(db_path) as connection:
        before = connection.execute(
            """
            SELECT scopes.generation_id, generations.max_text_chars,
                   COUNT(work.chunk_index)
            FROM memory_embedding_user_generations AS scopes
            JOIN memory_embedding_generations AS generations
              ON generations.generation_id = scopes.generation_id
            JOIN memory_embedding_work AS work
              ON work.user_id = scopes.user_id
             AND work.generation_id = scopes.generation_id
            WHERE scopes.user_id = 'user-1'
            GROUP BY scopes.generation_id, generations.max_text_chars
            """
        ).fetchone()
    assert before == (1, 50_000, 2)

    _apply_through(db_path, MIGRATION_0084)

    with sqlite3.connect(db_path) as connection:
        _configure_connection(connection, BUSY_TIMEOUT_MS)
        scope = connection.execute(
            """
            SELECT scopes.generation_id, scopes.state,
                   generations.max_text_chars
            FROM memory_embedding_user_generations AS scopes
            JOIN memory_embedding_generations AS generations
              ON generations.generation_id = scopes.generation_id
            WHERE scopes.user_id = 'user-1'
            """
        ).fetchone()
        work = connection.execute(
            """
            SELECT chunk_index, state
            FROM memory_embedding_work
            WHERE user_id = 'user-1'
            ORDER BY chunk_index
            """
        ).fetchall()
        old_storage = connection.execute(
            """
            SELECT name FROM sqlite_master
            WHERE name IN (
                'memory_embedding_entries_g1',
                'memory_embedding_vectors_g1'
            )
            """
        ).fetchall()
        connection.execute(
            """
            INSERT INTO memory_fragments(
                user_id, fragment_id, revision_id, source_path, block_kind,
                block_index, heading_path, content_text, content_sha256
            ) VALUES (
                'user-1', 'fragment-new', 'revision-0', 'new.md', 'paragraph',
                1, NULL, ?, ?
            )
            """,
            ("追" * 4_001, content_sha256("追" * 4_001)),
        )
        trigger_work = connection.execute(
            """
            SELECT chunk_index
            FROM memory_embedding_work
            WHERE user_id = 'user-1' AND fragment_id = 'fragment-new'
            ORDER BY chunk_index
            """
        ).fetchall()

    assert scope == (2, "building", 4_000)
    assert work == [(index, "pending") for index in range(15)]
    assert old_storage == []
    assert trigger_work == [(0,), (1,)]


def test_v84_fresh_database_keeps_current_bootstrap_generation(tmp_path: Path) -> None:
    db_path = tmp_path / "runtime.db"
    _apply_through(db_path, MIGRATION_0084)

    with sqlite3.connect(db_path) as connection:
        generation = connection.execute(
            """
            SELECT generation_id, max_text_chars
            FROM memory_embedding_generations
            """
        ).fetchone()
        version = connection.execute(
            """
            SELECT current_version FROM schema_versions
            WHERE component = 'local_runtime'
            """
        ).fetchone()

    assert generation == (1, 4_000)
    assert version == (84,)


def test_v84_keeps_wrong_active_until_current_build_activates(
    tmp_path: Path,
) -> None:
    db_path = _create_database_before_v71(tmp_path, users=("user-1",))
    _apply_through(db_path, MIGRATION_0083)
    with sqlite3.connect(db_path) as connection:
        _configure_connection(connection, BUSY_TIMEOUT_MS)
        with connection:
            connection.execute(
                """
                UPDATE memory_embedding_user_generations
                SET state = 'active', activated_at = ?, updated_at = ?
                WHERE user_id = 'user-1' AND generation_id = 1
                """,
                (TIMESTAMP, TIMESTAMP),
            )

    _apply_through(db_path, MIGRATION_0084)

    with sqlite3.connect(db_path) as connection:
        _configure_connection(connection, BUSY_TIMEOUT_MS)
        scopes_during_build = connection.execute(
            """
            SELECT scopes.state, scopes.generation_id,
                   generations.max_text_chars
            FROM memory_embedding_user_generations AS scopes
            JOIN memory_embedding_generations AS generations
              ON generations.generation_id = scopes.generation_id
            WHERE scopes.user_id = 'user-1'
            ORDER BY scopes.state
            """
        ).fetchall()
        chunks = split_memory_embedding_chunks(
            CONTENT, max_text_chars=MEMORY_EMBEDDING_MAX_TEXT_CHARS
        )
        with immediate_transaction(connection):
            for chunk in chunks:
                embedding_id = connection.execute(
                    """
                    INSERT INTO memory_embedding_entries_g2(
                        user_id, generation_id, fragment_id, chunk_index,
                        revision_id, fragment_content_sha256,
                        chunk_content_sha256, created_at
                    ) VALUES (
                        'user-1', 2, 'fragment-0', ?, 'revision-0', ?, ?, ?
                    )
                    """,
                    (
                        chunk.chunk_index,
                        CONTENT_SHA256,
                        chunk.content_sha256,
                        TIMESTAMP,
                    ),
                ).lastrowid
                connection.execute(
                    """
                    INSERT INTO memory_embedding_vectors_g2(
                        embedding_id, embedding, user_id, revision_id
                    ) VALUES (?, ?, 'user-1', 'revision-0')
                    """,
                    (embedding_id, sqlite3.Binary(b"\0" * 2_048)),
                )
            connection.execute(
                """
                DELETE FROM memory_embedding_work
                WHERE user_id = 'user-1' AND generation_id = 2
                """
            )
            activate_embedding_generation_in_transaction(
                connection,
                user_id="user-1",
                generation_id=2,
                activated_at=TIMESTAMP,
            )
        scopes_after_activation = connection.execute(
            """
            SELECT scopes.state, scopes.generation_id,
                   generations.max_text_chars
            FROM memory_embedding_user_generations AS scopes
            JOIN memory_embedding_generations AS generations
              ON generations.generation_id = scopes.generation_id
            WHERE scopes.user_id = 'user-1'
            """
        ).fetchall()
        old_generation = connection.execute(
            """
            SELECT generation_id FROM memory_embedding_generations
            WHERE generation_id = 1
            """
        ).fetchone()

    assert scopes_during_build == [
        ("active", 1, 50_000),
        ("building", 2, 4_000),
    ]
    assert scopes_after_activation == [("active", 2, 4_000)]
    assert old_generation is None


def test_v84_reuses_one_current_generation_for_multiple_users(
    tmp_path: Path,
) -> None:
    db_path = _create_database_before_v71(tmp_path, users=("user-1", "user-2"))
    _apply_through(db_path, MIGRATION_0084)

    with sqlite3.connect(db_path) as connection:
        scopes = connection.execute(
            """
            SELECT user_id, generation_id, state
            FROM memory_embedding_user_generations
            ORDER BY user_id
            """
        ).fetchall()
        generations = connection.execute(
            """
            SELECT generation_id, max_text_chars
            FROM memory_embedding_generations
            ORDER BY generation_id
            """
        ).fetchall()
        work_counts = connection.execute(
            """
            SELECT user_id, COUNT(*)
            FROM memory_embedding_work
            GROUP BY user_id
            ORDER BY user_id
            """
        ).fetchall()

    assert scopes == [
        ("user-1", 2, "building"),
        ("user-2", 2, "building"),
    ]
    assert generations == [(2, 4_000)]
    assert work_counts == [("user-1", 15), ("user-2", 15)]


def test_v84_keeps_existing_current_build_for_wrong_active(
    tmp_path: Path,
) -> None:
    db_path = _create_database_before_v71(tmp_path, users=("user-1",))
    _apply_through(db_path, MIGRATION_0083)
    with sqlite3.connect(db_path) as connection:
        _configure_connection(connection, BUSY_TIMEOUT_MS)
        with immediate_transaction(connection):
            connection.execute(
                """
                UPDATE memory_embedding_user_generations
                SET state = 'active', activated_at = ?, updated_at = ?
                WHERE user_id = 'user-1' AND generation_id = 1
                """,
                (TIMESTAMP, TIMESTAMP),
            )
            connection.execute(
                """
                INSERT INTO memory_embedding_generations(
                    generation_id, profile_id, model_id, dimensions,
                    normalized, distance_metric, max_text_chars, created_at
                ) SELECT 2, profile_id, model_id, dimensions, normalized,
                         distance_metric, 4000, ?
                  FROM memory_embedding_generations WHERE generation_id = 1
                """,
                (TIMESTAMP,),
            )
            create_embedding_generation_storage(
                connection,
                generation_id=2,
                dimensions=512,
            )
            connection.execute(
                """
                INSERT INTO memory_embedding_user_generations(
                    user_id, generation_id, state, created_at, updated_at
                ) VALUES ('user-1', 2, 'building', ?, ?)
                """,
                (TIMESTAMP, TIMESTAMP),
            )

    _apply_through(db_path, MIGRATION_0084)

    with sqlite3.connect(db_path) as connection:
        scopes = connection.execute(
            """
            SELECT state, generation_id
            FROM memory_embedding_user_generations
            WHERE user_id = 'user-1'
            ORDER BY state
            """
        ).fetchall()
        generations = connection.execute(
            "SELECT generation_id FROM memory_embedding_generations ORDER BY generation_id"
        ).fetchall()

    assert scopes == [("active", 1), ("building", 2)]
    assert generations == [(1,), (2,)]


def test_v84_preserves_1024_profile_identity(tmp_path: Path) -> None:
    db_path = _create_database_before_v71(tmp_path, users=("user-1",))
    _apply_through(db_path, MIGRATION_0083)
    with sqlite3.connect(db_path) as connection:
        _configure_connection(connection, BUSY_TIMEOUT_MS)
        with immediate_transaction(connection):
            connection.execute(
                "DELETE FROM memory_embedding_user_generations WHERE user_id='user-1'"
            )
            connection.execute(
                """
                INSERT INTO memory_embedding_generations(
                    generation_id, profile_id, model_id, dimensions,
                    normalized, distance_metric, max_text_chars, created_at
                ) VALUES (2, ?, ?, 1024, 1, 'cosine', 50000, ?)
                """,
                (
                    MEMORY_EMBEDDING_PROFILE_1024_ID,
                    MEMORY_EMBEDDING_MODEL_ID,
                    TIMESTAMP,
                ),
            )
            create_embedding_generation_storage(
                connection,
                generation_id=2,
                dimensions=1024,
            )
            connection.execute(
                """
                INSERT INTO memory_embedding_user_generations(
                    user_id, generation_id, state, created_at, updated_at
                ) VALUES ('user-1', 2, 'building', ?, ?)
                """,
                (TIMESTAMP, TIMESTAMP),
            )

    _apply_through(db_path, MIGRATION_0084)

    with sqlite3.connect(db_path) as connection:
        identity = connection.execute(
            """
            SELECT profile_id, model_id, dimensions, normalized,
                   distance_metric, max_text_chars
            FROM memory_embedding_generations
            """
        ).fetchone()
    assert identity == (
        MEMORY_EMBEDDING_PROFILE_1024_ID,
        MEMORY_EMBEDDING_MODEL_ID,
        1024,
        1,
        "cosine",
        4_000,
    )


def test_v84_rolls_back_generation_and_storage_creation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = _create_database_before_v71(tmp_path, users=("user-1",))
    _apply_through(db_path, MIGRATION_0083)
    migration = next(
        item for item in load_default_migrations() if item.name == MIGRATION_0084
    )
    original_create = rebase_migration.create_embedding_generation_storage

    def interrupt_after_storage_creation(
        connection: sqlite3.Connection,
        *,
        generation_id: int,
        dimensions: int,
    ) -> None:
        original_create(
            connection,
            generation_id=generation_id,
            dimensions=dimensions,
        )
        raise RuntimeError("simulated storage creation interruption")

    monkeypatch.setattr(
        rebase_migration,
        "create_embedding_generation_storage",
        interrupt_after_storage_creation,
    )
    with pytest.raises(MigrationError):
        apply_migrations(
            db_path=db_path,
            busy_timeout_ms=BUSY_TIMEOUT_MS,
            migrations=(migration,),
        )

    with sqlite3.connect(db_path) as connection:
        generation_rows = connection.execute(
            """
            SELECT generation_id, max_text_chars
            FROM memory_embedding_generations
            ORDER BY generation_id
            """
        ).fetchall()
        scope_rows = connection.execute(
            """
            SELECT user_id, generation_id, state
            FROM memory_embedding_user_generations
            """
        ).fetchall()
        new_storage = connection.execute(
            """
            SELECT name FROM sqlite_master
            WHERE name IN (
                'memory_embedding_entries_g2',
                'memory_embedding_vectors_g2'
            )
            """
        ).fetchall()
        version = connection.execute(
            """
            SELECT current_version FROM schema_versions
            WHERE component = 'local_runtime'
            """
        ).fetchone()

    assert generation_rows == [(1, 50_000)]
    assert scope_rows == [("user-1", 1, "building")]
    assert new_storage == []
    assert version == (83,)


def test_v84_rejects_missing_generation_storage_before_mutation(
    tmp_path: Path,
) -> None:
    db_path = _create_database_before_v71(tmp_path, users=("user-1",))
    _apply_through(db_path, MIGRATION_0083)
    with sqlite3.connect(db_path) as connection:
        _configure_connection(connection, BUSY_TIMEOUT_MS)
        with connection:
            connection.execute("DROP TABLE memory_embedding_vectors_g1")

    with pytest.raises(MigrationError, match="storage mismatch"):
        _apply_through(db_path, MIGRATION_0084)

    with sqlite3.connect(db_path) as connection:
        generation = connection.execute(
            "SELECT generation_id, max_text_chars FROM memory_embedding_generations"
        ).fetchall()
        scope = connection.execute(
            """
            SELECT user_id, generation_id, state
            FROM memory_embedding_user_generations
            """
        ).fetchall()
        version = connection.execute(
            """
            SELECT current_version FROM schema_versions
            WHERE component = 'local_runtime'
            """
        ).fetchone()

    assert generation == [(1, 50_000)]
    assert scope == [("user-1", 1, "building")]
    assert version == (83,)
