from __future__ import annotations

import json
from pathlib import Path

import pytest

from pantaray_agents.local_runtime.memory_catalog.connection import (
    open_memory_catalog_connection,
)
from pantaray_agents.local_runtime.memory_catalog.embedding_generations import (
    activate_embedding_generation,
    ensure_user_embedding_generation,
    start_embedding_reprojection,
)
from pantaray_agents.local_runtime.memory_catalog.reproject_embeddings import main
from pantaray_agents.local_runtime.runtime.runtime_env import (
    LOCAL_DB_BUSY_TIMEOUT_MS_ENV,
    LOCAL_DB_PATH_ENV,
)
from pantaray_agents.local_runtime.storage.migrations import (
    load_default_migrations,
)
from pantaray_agents.local_runtime.storage.transactions import immediate_transaction

from .embedding_test_support import TEST_EMBEDDING_SPECIFICATION, StubEmbeddingModel
from .migrated_db import prepare_test_database

BUSY_TIMEOUT_MS = 1_000
CLI = "pantaray_agents.local_runtime.memory_catalog.reproject_embeddings."


def test_cli_replaces_building_and_preserves_active_until_the_rebuild_lands(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
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
    active = ensure_user_embedding_generation(
        db_path=db_path,
        busy_timeout_ms=BUSY_TIMEOUT_MS,
        user_id="user-1",
        specification=TEST_EMBEDDING_SPECIFICATION,
    )
    activate_embedding_generation(
        db_path=db_path,
        busy_timeout_ms=BUSY_TIMEOUT_MS,
        user_id="user-1",
        generation_id=active.generation_id,
    )
    replaced = start_embedding_reprojection(
        db_path=db_path,
        busy_timeout_ms=BUSY_TIMEOUT_MS,
        user_id="user-1",
        specification=TEST_EMBEDDING_SPECIFICATION,
    )
    monkeypatch.setenv(LOCAL_DB_PATH_ENV, str(db_path))
    monkeypatch.setenv(LOCAL_DB_BUSY_TIMEOUT_MS_ENV, str(BUSY_TIMEOUT_MS))
    monkeypatch.setattr(
        CLI + "load_local_embedding_model", lambda: StubEmbeddingModel()
    )

    exit_code = main(("--user-id", "user-1"))

    output = json.loads(capsys.readouterr().out)
    with open_memory_catalog_connection(
        db_path=db_path, busy_timeout_ms=BUSY_TIMEOUT_MS
    ) as connection:
        scopes = connection.execute(
            """
            SELECT scopes.generation_id, scopes.state, generations.profile_id
            FROM memory_embedding_user_generations AS scopes
            JOIN memory_embedding_generations AS generations
              ON generations.generation_id = scopes.generation_id
            WHERE scopes.user_id = 'user-1'
            ORDER BY scopes.generation_id
            """
        ).fetchall()
        replaced_generation = connection.execute(
            "SELECT 1 FROM memory_embedding_generations WHERE generation_id = ?",
            (replaced.generation_id,),
        ).fetchone()
        replaced_table = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE name = ?",
            (f"memory_embedding_vectors_g{replaced.generation_id}",),
        ).fetchone()

    profile_id = TEST_EMBEDDING_SPECIFICATION.profile_id
    assert exit_code == 0
    assert output == {
        "generation_id": replaced.generation_id + 1,
        "profile_id": profile_id,
    }
    assert [tuple(row) for row in scopes] == [
        (active.generation_id, "active", profile_id),
        (replaced.generation_id + 1, "building", profile_id),
    ]
    assert replaced_generation is None
    assert replaced_table is None
