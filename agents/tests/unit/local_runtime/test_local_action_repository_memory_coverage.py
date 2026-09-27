from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from pantaray_agents.local_runtime.agent_state import LocalActionRepository
from pantaray_agents.local_runtime.memory_catalog.domain_registration import (
    register_inline_domain_memory,
)
from pantaray_agents.local_runtime.storage.memory_artifact_projection import (
    MemoryArtifactProjection,
    upsert_memory_artifact_projection,
)
from pantaray_agents.local_runtime.storage.migrations import (
    load_default_migrations,
)
from pantaray_agents.local_runtime.storage.transactions import immediate_transaction
from pantaray_agents.schema.repositories.repository import RepositoryErrorKind

from .migrated_db import prepare_test_database

BUSY_TIMEOUT_MS = 1_000
USER_ID = "user-1"
SUGGESTION_ID = "sug-1"


def _bootstrap_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "runtime.db"
    prepare_test_database(
        db_path=db_path,
        busy_timeout_ms=BUSY_TIMEOUT_MS,
        migrations=load_default_migrations(),
    )
    with sqlite3.connect(db_path) as connection:
        with connection:
            connection.execute(
                """
                INSERT INTO users(
                    user_id,
                    ui_language,
                    created_at,
                    updated_at
                ) VALUES (?, 'ja', '2026-03-24T00:00:00Z', '2026-03-24T00:00:00Z')
                """,
                (USER_ID,),
            )
            connection.execute(
                """
                INSERT INTO agent_suggestions(
                    suggestion_id,
                    user_id,
                    status,
                    answer,
                    prompt_text,
                    response_text,
                    prompt_name,
                    prompt_version,
                    has_suggestion,
                    interaction_contract,
                    created_at,
                    updated_at
                ) VALUES (?, ?, 'success', 'answer', 'prompt', 'response', 'prompt', 'v1', 1, 'action_offer', '2026-03-24T00:00:00Z', '2026-03-24T00:00:00Z')
                """,
                (SUGGESTION_ID, USER_ID),
            )
    return db_path


def _repo(db_path: Path) -> LocalActionRepository:
    return LocalActionRepository(
        db_path=db_path,
        busy_timeout_ms=BUSY_TIMEOUT_MS,
    )


def _insert_memory_artifact(
    connection: sqlite3.Connection,
    *,
    artifact_id: str,
    source_type: str,
    logical_created_at: str,
    logical_updated_at: str,
) -> None:
    connection.execute(
        """
        INSERT INTO memory_artifacts(
            artifact_id,
            user_id,
            source_type,
            source_record_id,
            root_path,
            content_sha256,
            logical_created_at,
            logical_updated_at,
            indexed_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            artifact_id,
            USER_ID,
            source_type,
            f"record-{artifact_id}",
            f"artifacts/{source_type}/{artifact_id}",
            f"sha-{artifact_id}",
            logical_created_at,
            logical_updated_at,
            logical_updated_at,
        ),
    )


@pytest.mark.asyncio
async def test_memory_source_coverage_ignores_legacy_artifact_projection(
    tmp_path: Path,
) -> None:
    db_path = _bootstrap_db(tmp_path)
    repo = _repo(db_path)
    with sqlite3.connect(db_path) as connection:
        with connection:
            _insert_memory_artifact(
                connection,
                artifact_id="artifact-facts-broken",
                source_type="facts",
                logical_created_at="2026-03-24T00:00:00Z",
                logical_updated_at="2026-03-24T00:05:00Z",
            )

    result = await repo.get_memory_source_coverage_snapshot(
        user_id=USER_ID,
        suggestion_created_at="2026-03-24T00:10:00Z",
        max_parallel_queries=1,
    )

    assert result.error is None
    assert result.data is not None
    facts_slot = next(
        slot for slot in result.data["slots"] if slot["source"] == "facts"
    )
    assert facts_slot["status"] == "missing"


@pytest.mark.asyncio
async def test_memory_source_coverage_fails_closed_for_non_artifact_catalog_head(
    tmp_path: Path,
) -> None:
    db_path = _bootstrap_db(tmp_path)
    repo = _repo(db_path)
    with sqlite3.connect(db_path) as connection:
        with immediate_transaction(connection):
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            register_inline_domain_memory(
                connection=connection,
                user_id=USER_ID,
                source="long_term_insight",
                source_record_id=USER_ID,
                content="invalid inline long-term insight",
            )

    result = await repo.get_memory_source_coverage_snapshot(
        user_id=USER_ID,
        suggestion_created_at="2026-03-24T00:20:00Z",
        max_parallel_queries=1,
    )

    assert result.data is None
    assert result.error is not None
    assert "long_term_insight coverage invariant violated" in result.error
    assert "current Catalog artifact revision is incomplete" in result.error
    assert result.error_kind is RepositoryErrorKind.CONSTRAINT
    assert result.retryable is False


@pytest.mark.asyncio
async def test_memory_source_coverage_treats_whitespace_only_artifact_as_missing(
    tmp_path: Path,
) -> None:
    db_path = _bootstrap_db(tmp_path)
    repo = _repo(db_path)
    upsert_memory_artifact_projection(
        db_path=str(db_path),
        busy_timeout_ms=BUSY_TIMEOUT_MS,
        projection=MemoryArtifactProjection(
            user_id=USER_ID,
            source_type="facts",
            source_record_id="facts-empty",
            root_path="memory/users/user-1/versions/facts-empty/facts",
            relative_path="facts/index.md",
            content=" \n\t\n",
            logical_created_at="2026-03-24T00:00:00Z",
            logical_updated_at="2026-03-24T00:05:00Z",
        ),
    )

    result = await repo.get_memory_source_coverage_snapshot(
        user_id=USER_ID,
        suggestion_created_at="2026-03-24T00:10:00Z",
        max_parallel_queries=1,
    )

    assert result.error is None
    assert result.data is not None
    facts_slot = next(
        slot for slot in result.data["slots"] if slot["source"] == "facts"
    )
    assert facts_slot["status"] == "missing"
