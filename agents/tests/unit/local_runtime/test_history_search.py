from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from pantaray_agents.local_runtime.storage.artifact_block_fts import (
    rebuild_memory_artifact_blocks_fts,
    search_memory_artifact_blocks,
)
from pantaray_agents.local_runtime.storage.migrations import (
    MigrationError,
    load_default_migrations,
)

from .migrated_db import prepare_test_database


def _seed_memory_artifact_blocks(db_path: Path) -> None:
    with sqlite3.connect(db_path) as connection:
        with connection:
            connection.execute(
                """
                INSERT INTO users(
                    user_id,
                    ui_language,
                    created_at,
                    updated_at
                ) VALUES (?, ?, ?, ?)
                """,
                (
                    "user-1",
                    "ja",
                    "2026-03-23T00:00:00Z",
                    "2026-03-23T00:00:00Z",
                ),
            )
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
                    "artifact-1",
                    "user-1",
                    "facts",
                    "fact-1",
                    "facts/artifact-1",
                    "sha256-artifact-1",
                    "2026-03-23T00:00:00Z",
                    "2026-03-23T00:00:00Z",
                    "2026-03-23T00:00:00Z",
                ),
            )
            connection.execute(
                """
                INSERT INTO memory_artifact_files(
                    file_id,
                    artifact_id,
                    relative_path,
                    sha256,
                    byte_size,
                    mime_type,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "file-1",
                    "artifact-1",
                    "facts/artifact-1/index.md",
                    "sha256-file-1",
                    128,
                    "text/markdown",
                    "2026-03-23T00:00:00Z",
                ),
            )
            connection.execute(
                """
                INSERT INTO memory_artifact_blocks(
                    block_id,
                    file_id,
                    block_kind,
                    heading_path,
                    block_index,
                    search_text,
                    preview_text,
                    start_offset,
                    end_offset
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "block-1",
                    "file-1",
                    "paragraph",
                    None,
                    0,
                    "local runtime migration checklist",
                    "local runtime migration checklist",
                    0,
                    33,
                ),
            )
            connection.execute(
                """
                INSERT INTO memory_artifact_blocks(
                    block_id,
                    file_id,
                    block_kind,
                    heading_path,
                    block_index,
                    search_text,
                    preview_text,
                    start_offset,
                    end_offset
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "block-2",
                    "file-1",
                    "paragraph",
                    None,
                    1,
                    "search projection rebuild pending",
                    "search projection rebuild pending",
                    34,
                    67,
                ),
            )


def test_rebuild_and_search_memory_artifact_blocks_fts(tmp_path: Path) -> None:
    db_path = tmp_path / "runtime.db"
    prepare_test_database(
        db_path=db_path,
        busy_timeout_ms=1_000,
        migrations=load_default_migrations(),
    )
    _seed_memory_artifact_blocks(db_path)

    indexed_count = rebuild_memory_artifact_blocks_fts(
        db_path=db_path,
        busy_timeout_ms=1_000,
    )
    assert indexed_count == 2

    results = search_memory_artifact_blocks(
        db_path=db_path,
        busy_timeout_ms=1_000,
        query="migration",
    )
    assert len(results) == 1
    assert results[0].block_id == "block-1"
    assert "migration" in results[0].snippet_text


def test_search_memory_artifact_blocks_rejects_empty_query(tmp_path: Path) -> None:
    db_path = tmp_path / "runtime.db"
    prepare_test_database(
        db_path=db_path,
        busy_timeout_ms=1_000,
        migrations=load_default_migrations(),
    )

    with pytest.raises(MigrationError, match="query must not be empty"):
        search_memory_artifact_blocks(
            db_path=db_path,
            busy_timeout_ms=1_000,
            query="   ",
        )
