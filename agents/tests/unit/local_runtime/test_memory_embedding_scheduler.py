from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

import pytest

from pantaray_agents.local_runtime.embedding_local import (
    LocalEmbeddingUnavailableError,
)
from pantaray_agents.local_runtime.memory_catalog.connection import (
    open_memory_catalog_connection,
)
from pantaray_agents.local_runtime.memory_catalog.domain_registration import (
    register_inline_domain_memory,
)
from pantaray_agents.local_runtime.memory_catalog.embedding_generations import (
    current_embedding_specification,
    ensure_user_embedding_generation,
)
from pantaray_agents.local_runtime.memory_catalog.embedding_work import (
    claim_due_embeddings,
)
from pantaray_agents.local_runtime.runtime.memory_embedding_scheduler import (
    MemoryEmbeddingProjectionResult,
    run_memory_embedding_projection,
)
from pantaray_agents.local_runtime.storage.migrations import (
    load_default_migrations,
)
from pantaray_agents.local_runtime.storage.transactions import immediate_transaction

from .embedding_test_support import (
    TEST_EMBEDDING_MANIFEST,
    StubEmbeddingModel,
    build_test_manifest,
)
from .migrated_db import prepare_test_database

SCHEDULER = "pantaray_agents.local_runtime.runtime.memory_embedding_scheduler."


class StopAfterFirstChunk(StubEmbeddingModel):
    """Stops the pass the way a shutdown would, once one chunk is indexed."""

    def __init__(self, manifest, stop_event: threading.Event) -> None:
        super().__init__(manifest)
        self._stop_event = stop_event

    def embed_documents(self, texts):
        self._stop_event.set()
        return super().embed_documents(texts)


def _create_pending_fragment(db_path: Path) -> str:
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
                content="Remember the verified deployment result.",
            )
        row = connection.execute(
            """
            SELECT fragment_id FROM memory_fragments
            WHERE block_kind NOT IN ('record_root', 'document_root')
            """
        ).fetchone()
    assert row is not None
    return str(row[0])


def _add_fragment(db_path: Path, *, source_record_id: str, content: str) -> None:
    with open_memory_catalog_connection(
        db_path=db_path, busy_timeout_ms=1_000
    ) as connection:
        with immediate_transaction(connection):
            register_inline_domain_memory(
                connection=connection,
                user_id="user-1",
                source="activity_log",
                source_record_id=source_record_id,
                content=content,
            )


def _scopes(db_path: Path) -> list[tuple[str, str]]:
    with open_memory_catalog_connection(
        db_path=db_path, busy_timeout_ms=1_000
    ) as connection:
        return [
            (str(row[0]), str(row[1]))
            for row in connection.execute(
                """
                SELECT scopes.state, generations.profile_id
                FROM memory_embedding_user_generations AS scopes
                JOIN memory_embedding_generations AS generations
                  ON generations.generation_id = scopes.generation_id
                WHERE scopes.user_id = 'user-1'
                ORDER BY scopes.state
                """
            ).fetchall()
        ]


def _active_generation_id(db_path: Path) -> int:
    with open_memory_catalog_connection(
        db_path=db_path, busy_timeout_ms=1_000
    ) as connection:
        row = connection.execute(
            """
            SELECT generation_id FROM memory_embedding_user_generations
            WHERE user_id = 'user-1' AND state = 'active'
            """
        ).fetchone()
    assert row is not None
    return int(row[0])


def _install_model(
    monkeypatch: pytest.MonkeyPatch, model: StubEmbeddingModel
) -> StubEmbeddingModel:
    monkeypatch.setattr(SCHEDULER + "load_local_embedding_model", lambda: model)
    return model


def test_projection_embeds_the_chunk_and_commits_it(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "runtime.db"
    fragment_id = _create_pending_fragment(db_path)
    model = _install_model(monkeypatch, StubEmbeddingModel())

    result = run_memory_embedding_projection(
        db_path=db_path,
        busy_timeout_ms=1_000,
        user_id="user-1",
    )

    with sqlite3.connect(db_path) as connection:
        generation_id, profile_id = connection.execute(
            """
            SELECT generations.generation_id, generations.profile_id
            FROM memory_embedding_user_generations AS scopes
            JOIN memory_embedding_generations AS generations
              ON generations.generation_id = scopes.generation_id
            WHERE scopes.user_id = 'user-1'
            """
        ).fetchone()
        indexed = connection.execute(
            f"SELECT fragment_id FROM memory_embedding_entries_g{generation_id}"
        ).fetchall()
        work_count = connection.execute(
            "SELECT COUNT(*) FROM memory_embedding_work"
        ).fetchone()[0]
    assert result.selected_count == 1
    assert result.indexed_count == 1
    assert result.failed_count == 0
    assert model.documents == [["Remember the verified deployment result."]]
    assert indexed == [(fragment_id,)]
    assert work_count == 0
    assert profile_id == TEST_EMBEDDING_MANIFEST.profile_id


def test_projection_without_a_model_indexes_nothing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "runtime.db"
    _create_pending_fragment(db_path)

    def unavailable() -> StubEmbeddingModel:
        raise LocalEmbeddingUnavailableError("model directory is not set")

    monkeypatch.setattr(SCHEDULER + "load_local_embedding_model", unavailable)

    result = run_memory_embedding_projection(
        db_path=db_path,
        busy_timeout_ms=1_000,
        user_id="user-1",
    )

    with sqlite3.connect(db_path) as connection:
        scopes = connection.execute(
            "SELECT COUNT(*) FROM memory_embedding_user_generations"
        ).fetchone()[0]
        work_count = connection.execute(
            "SELECT COUNT(*) FROM memory_embedding_work"
        ).fetchone()[0]
    assert result == MemoryEmbeddingProjectionResult(0, 0, 0)
    assert scopes == 0
    assert work_count == 0


def test_new_artifact_revision_rebuilds_and_replaces_the_active_generation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "runtime.db"
    _create_pending_fragment(db_path)
    _add_fragment(db_path, source_record_id="activity-2", content="A second note.")
    _install_model(monkeypatch, StubEmbeddingModel())
    run_memory_embedding_projection(
        db_path=db_path, busy_timeout_ms=1_000, user_id="user-1"
    )
    assert _scopes(db_path) == [("active", TEST_EMBEDDING_MANIFEST.profile_id)]
    superseded_id = _active_generation_id(db_path)

    replacement = build_test_manifest(artifact_revision="fedcba9876543210")
    stopped = threading.Event()
    interrupted = StopAfterFirstChunk(replacement, stopped)
    _install_model(monkeypatch, interrupted)
    partial = run_memory_embedding_projection(
        db_path=db_path,
        busy_timeout_ms=1_000,
        user_id="user-1",
        stop_event=stopped,
    )
    while_building = _scopes(db_path)

    _install_model(monkeypatch, StubEmbeddingModel(replacement))
    finished = run_memory_embedding_projection(
        db_path=db_path, busy_timeout_ms=1_000, user_id="user-1"
    )

    assert partial.indexed_count == 1
    assert finished.indexed_count == 1
    # The old index answers searches until the replacement is complete, and is
    # dropped with its vectors once it is.
    assert while_building == [
        ("active", TEST_EMBEDDING_MANIFEST.profile_id),
        ("building", replacement.profile_id),
    ]
    assert _scopes(db_path) == [("active", replacement.profile_id)]
    with sqlite3.connect(db_path) as connection:
        superseded_storage = connection.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE name = ?",
            (f"memory_embedding_entries_g{superseded_id}",),
        ).fetchone()[0]
        generation_rows = connection.execute(
            "SELECT COUNT(*) FROM memory_embedding_generations"
        ).fetchone()[0]
    assert superseded_storage == 0
    assert generation_rows == 1


def test_corrupt_fragment_hash_fails_before_the_model_is_called(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "runtime.db"
    _create_pending_fragment(db_path)
    model = _install_model(monkeypatch, StubEmbeddingModel())
    with open_memory_catalog_connection(
        db_path=db_path, busy_timeout_ms=1_000
    ) as connection:
        with immediate_transaction(connection):
            connection.execute(
                """
                UPDATE memory_fragments
                SET content_sha256 = ?
                WHERE block_kind NOT IN ('record_root', 'document_root')
                """,
                ("f" * 64,),
            )

    result = run_memory_embedding_projection(
        db_path=db_path,
        busy_timeout_ms=1_000,
        user_id="user-1",
    )

    with sqlite3.connect(db_path) as connection:
        work = connection.execute(
            "SELECT state, last_error_code FROM memory_embedding_work"
        ).fetchone()
    assert result.failed_count == 1
    assert model.documents == []
    assert work == ("failed", "MEMORY_EMBEDDING_CONTENT_HASH_INVALID")


def test_claiming_is_limited_to_the_generation_the_model_builds(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "runtime.db"
    _create_pending_fragment(db_path)
    _install_model(monkeypatch, StubEmbeddingModel())
    for _ in range(2):
        run_memory_embedding_projection(
            db_path=db_path, busy_timeout_ms=1_000, user_id="user-1"
        )
    superseded_id = _active_generation_id(db_path)

    replacement = build_test_manifest(artifact_revision="fedcba9876543210")
    building = ensure_user_embedding_generation(
        db_path=db_path,
        busy_timeout_ms=1_000,
        user_id="user-1",
        specification=current_embedding_specification(replacement),
    )
    # A fragment written during a rebuild is enqueued for the active generation
    # as well, and that row outlives the one being built.
    _add_fragment(db_path, source_record_id="activity-2", content="A later note.")
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            "DELETE FROM memory_embedding_work WHERE generation_id = ?",
            (building.generation_id,),
        )

    claimed = claim_due_embeddings(
        db_path=db_path,
        busy_timeout_ms=1_000,
        user_id="user-1",
        generation_id=building.generation_id,
        now="2026-09-19T00:00:00.000Z",
        limit=1,
    )

    assert building.generation_id != superseded_id
    assert _work_rows(db_path, generation_id=superseded_id) >= 1
    # Claiming that row would embed it with the new model and store the vector
    # in the index the previous artifact built, which nothing downstream checks.
    assert claimed == ()


def _work_rows(db_path: Path, *, generation_id: int) -> int:
    with sqlite3.connect(db_path) as connection:
        return int(
            connection.execute(
                "SELECT COUNT(*) FROM memory_embedding_work WHERE generation_id = ?",
                (generation_id,),
            ).fetchone()[0]
        )


def test_an_unembeddable_chunk_does_not_hold_the_generation_back(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "runtime.db"
    _create_pending_fragment(db_path)
    # A code block with a long run of blanks in the middle: one of its chunks
    # has nothing to embed. The production chunk length is far shorter than the
    # one these tests use, so this is more likely there, not less.
    _add_fragment(
        db_path,
        source_record_id="blank-run",
        content="```\n" + "あ" * 3_990 + "\n" + " " * 4_200 + "\nend\n```",
    )
    _install_model(monkeypatch, StubEmbeddingModel())

    results = [
        run_memory_embedding_projection(
            db_path=db_path, busy_timeout_ms=1_000, user_id="user-1"
        )
        for _ in range(6)
    ]

    with sqlite3.connect(db_path) as connection:
        remaining = connection.execute(
            "SELECT state, last_error_code FROM memory_embedding_work"
        ).fetchall()
    assert [tuple(row) for row in remaining] == [
        ("failed", "MEMORY_EMBEDDING_CONTENT_EMPTY")
    ]
    assert sum(result.indexed_count for result in results) == 3
    # Leaving the generation in `building` would switch semantic search off for
    # this owner permanently, over one chunk with nothing in it.
    assert _scopes(db_path) == [("active", TEST_EMBEDDING_MANIFEST.profile_id)]


def test_a_production_sized_chunk_length_indexes_every_chunk(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The catalog tests use a 4,000 character chunk; a real profile measures a
    # much shorter one, which splits the same fragment many more ways.
    short_chunks = build_test_manifest(
        artifact_revision="00112233445566aa", max_text_chars=256
    )
    db_path = tmp_path / "runtime.db"
    _create_pending_fragment(db_path)
    _add_fragment(db_path, source_record_id="long", content="記憶検索の設計。" * 400)
    model = _install_model(monkeypatch, StubEmbeddingModel(short_chunks))

    result = run_memory_embedding_projection(
        db_path=db_path, busy_timeout_ms=1_000, user_id="user-1"
    )

    with sqlite3.connect(db_path) as connection:
        remaining = connection.execute(
            "SELECT COUNT(*) FROM memory_embedding_work"
        ).fetchone()[0]
    assert result.indexed_count == 14
    assert all(len(batch[0]) <= 256 for batch in model.documents)
    assert sum(len(batch[0]) for batch in model.documents) == 3_240
    assert remaining == 0
    assert _scopes(db_path) == [("active", short_chunks.profile_id)]
