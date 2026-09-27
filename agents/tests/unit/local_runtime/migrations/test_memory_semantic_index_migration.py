from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from pantaray_agents.local_runtime.memory_catalog.embedding_generations import (
    EmbeddingSpecification,
    ensure_user_embedding_generation,
)
from pantaray_agents.local_runtime.storage.migrations import MigrationError
from pantaray_agents.local_runtime.storage.migrations import runner as migration_runner

from .support import (
    _configure_connection,
    _insert_user,
    _migrations_before,
    apply_migrations,
    load_default_migrations,
)

MIGRATION_NAME = "0071_memory_semantic_index.sql"
# These tests run against the schema as it stood before the local embedding
# cutover, where the profile id column still only accepted the Titan profiles.
PRE_CUTOVER_SPECIFICATION = EmbeddingSpecification(
    profile_id="memory.titan-text-v2-512.v1",
    model_id="amazon.titan-embed-text-v2:0",
    dimensions=512,
    normalized=True,
    max_text_chars=4_000,
)
BUSY_TIMEOUT_MS = 1_000
CONTENT_SHA256 = "a" * 64


def _insert_revision(connection: sqlite3.Connection) -> None:
    _insert_user(connection, "user-1")
    connection.execute(
        """
        INSERT INTO memory_nodes(
            user_id, node_id, source_type, source_record_id, lifecycle,
            integrity, current_revision_id, created_at, updated_at
        ) VALUES (
            'user-1', 'node-1', 'fact', 'fact-1', 'preparing', 'healthy', NULL,
            '2026-08-09T00:00:00Z', '2026-08-09T00:00:00Z'
        )
        """
    )
    connection.execute(
        """
        INSERT INTO memory_revisions(
            user_id, revision_id, node_id, body_kind, inline_body,
            artifact_root_path, fragment_schema_version, content_sha256,
            created_at, profile_brief
        ) VALUES (
            'user-1', 'revision-1', 'node-1', 'inline', 'memory body', NULL,
            1, ?, '2026-08-09T00:00:00Z', NULL
        )
        """,
        (CONTENT_SHA256,),
    )
    connection.execute(
        """
        UPDATE memory_nodes
        SET lifecycle = 'active', current_revision_id = 'revision-1'
        WHERE user_id = 'user-1' AND node_id = 'node-1'
        """
    )


def _insert_fragment(
    connection: sqlite3.Connection,
    *,
    fragment_id: str,
    block_kind: str,
    block_index: int,
) -> None:
    connection.execute(
        """
        INSERT INTO memory_fragments(
            user_id, fragment_id, revision_id, source_path, block_kind,
            block_index, heading_path, content_text, content_sha256
        ) VALUES (
            'user-1', ?, 'revision-1', 'memory.md', ?, ?, NULL,
            'memory body', ?
        )
        """,
        (fragment_id, block_kind, block_index, CONTENT_SHA256),
    )


def test_memory_semantic_index_backfills_non_root_and_triggers_new_work(
    tmp_path: Path,
) -> None:
    migrations = load_default_migrations()
    db_path = tmp_path / "runtime.db"
    apply_migrations(
        db_path=db_path,
        busy_timeout_ms=BUSY_TIMEOUT_MS,
        migrations=_migrations_before(migrations, MIGRATION_NAME),
    )
    with sqlite3.connect(db_path) as connection:
        _configure_connection(connection, BUSY_TIMEOUT_MS)
        _insert_revision(connection)
        _insert_fragment(
            connection,
            fragment_id="fragment-document-root",
            block_kind="document_root",
            block_index=0,
        )
        _insert_fragment(
            connection,
            fragment_id="fragment-paragraph",
            block_kind="paragraph",
            block_index=1,
        )

    apply_migrations(
        db_path=db_path,
        busy_timeout_ms=BUSY_TIMEOUT_MS,
        migrations=migrations,
    )

    with sqlite3.connect(db_path) as connection:
        _configure_connection(connection, BUSY_TIMEOUT_MS)
        backfilled = connection.execute(
            """
            SELECT generation_id, fragment_id, chunk_index, state, last_error_code
            FROM memory_embedding_work ORDER BY fragment_id
            """
        ).fetchall()
        _insert_fragment(
            connection,
            fragment_id="fragment-heading",
            block_kind="heading",
            block_index=2,
        )
        _insert_fragment(
            connection,
            fragment_id="fragment-later-root",
            block_kind="document_root",
            block_index=3,
        )
        work_ids = {
            str(row[0])
            for row in connection.execute(
                "SELECT fragment_id FROM memory_embedding_work"
            )
        }

    assert backfilled == [(2, "fragment-paragraph", 0, "pending", None)]
    assert work_ids == {"fragment-paragraph", "fragment-heading"}


def test_memory_semantic_index_children_cascade_with_fragment(tmp_path: Path) -> None:
    db_path = tmp_path / "runtime.db"
    apply_migrations(
        db_path=db_path,
        busy_timeout_ms=BUSY_TIMEOUT_MS,
        migrations=load_default_migrations(),
    )
    with sqlite3.connect(db_path) as connection:
        _configure_connection(connection, BUSY_TIMEOUT_MS)
        _insert_revision(connection)
        connection.commit()
        ensure_user_embedding_generation(
            db_path=db_path,
            busy_timeout_ms=BUSY_TIMEOUT_MS,
            user_id="user-1",
            specification=PRE_CUTOVER_SPECIFICATION,
        )
        _insert_fragment(
            connection,
            fragment_id="fragment-paragraph",
            block_kind="paragraph",
            block_index=1,
        )
        embedding_id = connection.execute(
            """
            INSERT INTO memory_embedding_entries_g1(
                user_id, generation_id, fragment_id, chunk_index, revision_id,
                fragment_content_sha256, chunk_content_sha256, created_at
            ) VALUES (
                'user-1', 1, 'fragment-paragraph', 0, 'revision-1', ?, ?,
                '2026-08-09T00:00:00Z'
            )
            """,
            (CONTENT_SHA256, CONTENT_SHA256),
        ).lastrowid
        connection.execute(
            """
            INSERT INTO memory_embedding_vectors_g1(
                embedding_id, embedding, user_id, revision_id
            ) VALUES (?, ?, 'user-1', 'revision-1')
            """,
            (embedding_id, sqlite3.Binary(b"\0" * 2048)),
        )
        connection.execute(
            "DELETE FROM memory_fragments WHERE fragment_id = 'fragment-paragraph'"
        )
        work_count = connection.execute(
            "SELECT COUNT(*) FROM memory_embedding_work"
        ).fetchone()[0]
        embedding_count = connection.execute(
            "SELECT COUNT(*) FROM memory_embedding_entries_g1"
        ).fetchone()[0]
        vector_count = connection.execute(
            "SELECT COUNT(*) FROM memory_embedding_vectors_g1"
        ).fetchone()[0]

    assert work_count == 0
    assert embedding_count == 0
    assert vector_count == 0


def test_memory_semantic_index_migration_is_atomic_and_retryable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "runtime.db"
    migrations = load_default_migrations()
    apply_migrations(
        db_path=db_path,
        busy_timeout_ms=BUSY_TIMEOUT_MS,
        migrations=_migrations_before(migrations, MIGRATION_NAME),
    )
    migration = next(item for item in migrations if item.name == MIGRATION_NAME)
    original_execute = migration_runner.execute_sql_statements

    def interrupt_after_vec_table_creation(
        connection: sqlite3.Connection,
        statements: tuple[str, ...],
    ) -> None:
        for statement in statements:
            connection.execute(statement)
            if "CREATE VIRTUAL TABLE memory_embedding_vectors_g1" in statement:
                raise RuntimeError("simulated interruption")
        raise AssertionError("vec0 migration statement was not executed")

    monkeypatch.setattr(
        migration_runner,
        "execute_sql_statements",
        interrupt_after_vec_table_creation,
    )
    with pytest.raises(MigrationError):
        apply_migrations(
            db_path=db_path,
            busy_timeout_ms=BUSY_TIMEOUT_MS,
            migrations=(migration,),
        )

    with sqlite3.connect(db_path) as connection:
        tables = connection.execute(
            """
            SELECT name FROM sqlite_master
            WHERE name LIKE 'memory_embedding_%'
            """
        ).fetchall()
        version = connection.execute(
            """
            SELECT current_version FROM schema_versions
            WHERE component = 'local_runtime'
            """
        ).fetchone()
    assert tables == []
    assert version == (70,)

    monkeypatch.setattr(
        migration_runner,
        "execute_sql_statements",
        original_execute,
    )
    apply_migrations(
        db_path=db_path,
        busy_timeout_ms=BUSY_TIMEOUT_MS,
        migrations=(migration,),
    )
