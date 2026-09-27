from __future__ import annotations

import sqlite3
from pathlib import Path

from .support import (
    _insert_user,
    _migrations_before,
    apply_migrations,
    load_default_migrations,
)

MIGRATION_NAME = "0070_memory_revision_profile_brief.sql"


def test_memory_revision_profile_brief_migration_adds_revision_owned_brief(
    tmp_path: Path,
) -> None:
    migrations = load_default_migrations()
    migration_index = next(
        index
        for index, migration in enumerate(migrations)
        if migration.name == MIGRATION_NAME
    )
    migrations_through_profile_brief = migrations[: migration_index + 1]
    db_path = tmp_path / "runtime.db"
    apply_migrations(
        db_path=db_path,
        busy_timeout_ms=1_000,
        migrations=migrations_through_profile_brief,
    )

    with sqlite3.connect(db_path) as connection:
        columns = {
            str(row[1])
            for row in connection.execute("PRAGMA table_info(memory_revisions)")
        }

    assert "profile_brief" in columns


def test_memory_revision_profile_brief_migration_backfills_current_fact(
    tmp_path: Path,
) -> None:
    migrations = load_default_migrations()
    db_path = tmp_path / "runtime.db"
    apply_migrations(
        db_path=db_path,
        busy_timeout_ms=1_000,
        migrations=_migrations_before(migrations, MIGRATION_NAME),
    )
    with sqlite3.connect(db_path) as connection:
        _insert_user(connection, "user-1")
        connection.execute(
            """
            INSERT INTO memory_nodes(
                user_id, node_id, source_type, source_record_id, lifecycle,
                integrity, current_revision_id, created_at, updated_at
            ) VALUES (
                'user-1', 'node-1', 'fact', 'fact-1', 'active', 'healthy',
                'revision-1', '2026-08-09T00:00:00Z', '2026-08-09T00:00:00Z'
            )
            """
        )
        connection.execute(
            """
            INSERT INTO memory_revisions(
                user_id, revision_id, node_id, body_kind, artifact_root_path,
                fragment_schema_version, content_sha256, created_at
            ) VALUES (
                'user-1', 'revision-1', 'node-1', 'artifact_tree',
                'memory_catalog/revision-1', 1, 'sha-current',
                '2026-08-09T00:00:00Z'
            )
            """
        )
        connection.execute(
            """
            INSERT INTO agent_facts(
                fact_id, user_id, status, facts_profile_brief, prompt_name,
                prompt_version, structured_fact_sha256, created_at, updated_at
            ) VALUES (
                'fact-1', 'user-1', 'success', 'revision-owned brief',
                'fact_structuring', '1.0', 'sha-current',
                '2026-08-09T00:00:00Z', '2026-08-09T00:00:00Z'
            )
            """
        )
        connection.execute(
            """
            INSERT INTO agent_facts(
                fact_id, user_id, status, facts_profile_brief, prompt_name,
                prompt_version, structured_fact_sha256, created_at, updated_at
            ) VALUES (
                'other-fact', 'user-1', 'success', 'wrong same-sha brief',
                'fact_structuring', '1.0', 'sha-current',
                '9999-01-01T00:00:00Z', '9999-01-01T00:00:00Z'
            )
            """
        )
    apply_migrations(
        db_path=db_path,
        busy_timeout_ms=1_000,
        migrations=migrations,
    )

    with sqlite3.connect(db_path) as connection:
        brief = connection.execute(
            "SELECT profile_brief FROM memory_revisions WHERE revision_id = 'revision-1'"
        ).fetchone()[0]

    assert brief == "revision-owned brief"


def test_memory_revision_profile_brief_migration_backfills_current_insight(
    tmp_path: Path,
) -> None:
    migrations = load_default_migrations()
    db_path = tmp_path / "runtime.db"
    apply_migrations(
        db_path=db_path,
        busy_timeout_ms=1_000,
        migrations=_migrations_before(migrations, MIGRATION_NAME),
    )
    with sqlite3.connect(db_path) as connection:
        _insert_user(connection, "user-1")
        connection.execute(
            """
            INSERT INTO memory_nodes(
                user_id, node_id, source_type, source_record_id, lifecycle,
                integrity, current_revision_id, created_at, updated_at
            ) VALUES (
                'user-1', 'node-1', 'long_term_insight', 'user-1', 'active',
                'healthy', 'revision-1', '2026-08-09T00:00:00Z',
                '2026-08-09T00:00:00Z'
            )
            """
        )
        connection.execute(
            """
            INSERT INTO memory_revisions(
                user_id, revision_id, node_id, body_kind, artifact_root_path,
                fragment_schema_version, content_sha256, created_at
            ) VALUES (
                'user-1', 'revision-1', 'node-1', 'artifact_tree',
                'memory_catalog/revision-1', 1, 'sha-current',
                '2026-08-09T00:00:00Z'
            )
            """
        )
        connection.execute(
            """
            INSERT INTO agent_long_term_insight_state(
                user_id, source_run_id, storage_path, sha256,
                insight_profile_brief, created_at, updated_at
            ) VALUES (
                'user-1', 'run-1', 'memory_catalog/revision-1/insights/index.md',
                'sha-current', 'revision-owned insight brief',
                '2026-08-09T00:00:00Z', '2026-08-09T00:00:00Z'
            )
            """
        )
    apply_migrations(
        db_path=db_path,
        busy_timeout_ms=1_000,
        migrations=migrations,
    )

    with sqlite3.connect(db_path) as connection:
        brief = connection.execute(
            "SELECT profile_brief FROM memory_revisions WHERE revision_id = 'revision-1'"
        ).fetchone()[0]

    assert brief == "revision-owned insight brief"
