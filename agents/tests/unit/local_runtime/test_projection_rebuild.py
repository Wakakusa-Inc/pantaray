from __future__ import annotations

import sqlite3
from pathlib import Path

from pantaray_agents.local_runtime.storage.memory_artifact_projection import (
    MemoryArtifactProjection,
    upsert_memory_artifact_projection,
)
from pantaray_agents.local_runtime.storage.migrations import (
    load_default_migrations,
)
from pantaray_agents.local_runtime.storage.projection_rebuild import (
    enqueue_fts_rebuild_job,
    rebuild_memory_artifact_fts_projection,
    run_next_pending_fts_rebuild_job,
)

from .migrated_db import prepare_test_database


def _seed_block(db_path: Path) -> None:
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
                    "projection rebuild text",
                    "projection rebuild text",
                    0,
                    23,
                ),
            )


def test_rebuild_memory_artifact_fts_projection_records_completed_fts_job(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "runtime.db"
    prepare_test_database(
        db_path=db_path,
        busy_timeout_ms=1_000,
        migrations=load_default_migrations(),
    )
    _seed_block(db_path)

    fts_job_id = rebuild_memory_artifact_fts_projection(
        db_path=db_path,
        busy_timeout_ms=1_000,
    )

    with sqlite3.connect(db_path) as connection:
        row = connection.execute(
            "SELECT status, completed_at FROM fts_jobs WHERE fts_job_id = ?",
            (fts_job_id,),
        ).fetchone()
        indexed_count_row = connection.execute(
            "SELECT count(*) FROM memory_artifact_blocks_fts"
        ).fetchone()

    assert row is not None
    assert row[0] == "completed"
    assert row[1] is not None
    assert indexed_count_row is not None
    assert int(indexed_count_row[0]) == 1


def test_upsert_memory_artifact_projection_updates_fts_rows_incrementally(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "runtime.db"
    prepare_test_database(
        db_path=db_path,
        busy_timeout_ms=1_000,
        migrations=load_default_migrations(),
    )
    _insert_user(db_path)
    _upsert_projection(
        db_path=db_path,
        source_record_id="fact-1",
        content="# Facts\n- Alpha original\n",
    )
    _upsert_projection(
        db_path=db_path,
        source_record_id="fact-2",
        content="# Facts\n- Beta retained\n",
    )

    _upsert_projection(
        db_path=db_path,
        source_record_id="fact-1",
        content="# Facts\n- Alpha updated\n",
    )

    with sqlite3.connect(db_path) as connection:
        alpha_old = _fts_match_count(connection, "original")
        alpha_new = _fts_match_count(connection, "updated")
        beta_retained = _fts_match_count(connection, "retained")

    assert alpha_old == 0
    assert alpha_new == 1
    assert beta_retained == 1


def test_run_next_pending_fts_rebuild_job_processes_enqueued_job(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "runtime.db"
    prepare_test_database(
        db_path=db_path,
        busy_timeout_ms=1_000,
        migrations=load_default_migrations(),
    )
    _seed_block(db_path)
    fts_job_id = enqueue_fts_rebuild_job(
        db_path=db_path,
        busy_timeout_ms=1_000,
    )

    processed = run_next_pending_fts_rebuild_job(
        db_path=db_path,
        busy_timeout_ms=1_000,
    )

    assert processed is True
    with sqlite3.connect(db_path) as connection:
        row = connection.execute(
            "SELECT status, started_at, completed_at FROM fts_jobs WHERE fts_job_id = ?",
            (fts_job_id,),
        ).fetchone()
    assert row is not None
    assert row[0] == "completed"
    assert row[1] is not None
    assert row[2] is not None


def _insert_user(db_path: Path) -> None:
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


def _upsert_projection(
    *,
    db_path: Path,
    source_record_id: str,
    content: str,
) -> None:
    upsert_memory_artifact_projection(
        db_path=str(db_path),
        busy_timeout_ms=1_000,
        projection=MemoryArtifactProjection(
            user_id="user-1",
            source_type="facts",
            source_record_id=source_record_id,
            root_path=f"memory/users/user-1/versions/{source_record_id}",
            relative_path="structured_facts.md",
            content=content,
            logical_created_at="2026-03-23T00:00:00Z",
            logical_updated_at="2026-03-23T00:00:00Z",
        ),
    )


def _fts_match_count(connection: sqlite3.Connection, query: str) -> int:
    row = connection.execute(
        """
        SELECT count(*)
        FROM memory_artifact_blocks_fts
        WHERE memory_artifact_blocks_fts MATCH ?
        """,
        (query,),
    ).fetchone()
    assert row is not None
    return int(row[0])
