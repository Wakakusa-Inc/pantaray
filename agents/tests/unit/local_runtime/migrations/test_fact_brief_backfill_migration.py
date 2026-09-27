from __future__ import annotations

import sqlite3
from pathlib import Path

from .support import (
    FACT_BRIEF_BACKFILL_MIGRATION_NAME,
    _configure_connection,
    _insert_user,
    _migrations_before,
    apply_migrations,
    load_default_migrations,
)


def test_fact_brief_backfill_seeds_run_cache_from_legacy_facts(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "runtime.db"
    migrations = load_default_migrations()
    apply_migrations(
        db_path=db_path,
        busy_timeout_ms=1_000,
        migrations=_migrations_before(migrations, FACT_BRIEF_BACKFILL_MIGRATION_NAME),
    )
    with sqlite3.connect(db_path) as connection:
        _configure_connection(connection, busy_timeout_ms=1_000)
        with connection:
            _insert_user(connection, "user-1")
            connection.execute(
                """
                INSERT INTO agent_facts(
                    fact_id,
                    user_id,
                    status,
                    facts_profile_brief,
                    prompt_name,
                    prompt_version,
                    source_insight_ids,
                    created_at,
                    updated_at
                ) VALUES (?, ?, 'success', ?, 'fact_structuring', '1.0', '[]', ?, ?)
                """,
                (
                    "fact-legacy",
                    "user-1",
                    "legacy brief",
                    "2026-06-21T00:00:00Z",
                    "2026-06-22T00:00:00Z",
                ),
            )

    apply_migrations(
        db_path=db_path,
        busy_timeout_ms=1_000,
        migrations=migrations,
    )

    with sqlite3.connect(db_path) as connection:
        _configure_connection(connection, busy_timeout_ms=1_000)
        row = connection.execute(
            """
            SELECT fact_run_id, fact_id, status, facts_profile_brief, created_at, updated_at
            FROM agent_fact_structuring_runs
            WHERE fact_id = 'fact-legacy'
            """
        ).fetchone()

    assert row == (
        "legacy-fact-legacy",
        "fact-legacy",
        "success",
        "legacy brief",
        "2026-06-21T00:00:00Z",
        "2026-06-22T00:00:00Z",
    )
