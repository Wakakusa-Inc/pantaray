from __future__ import annotations

import sqlite3
from pathlib import Path

from pantaray_agents.local_runtime.storage.migrations import (
    apply_migrations,
    load_default_migrations,
)

BUSY_TIMEOUT_MS = 1_000
USER_ID = "user-1"
CONSUMPTION_MIGRATION = "0079_fact_activity_consumptions.sql"


def test_consumption_migration_converts_checkpoint_and_removes_cursor_table(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "runtime.sqlite3"
    migrations = load_default_migrations()
    consumption_migration = next(
        migration for migration in migrations if migration.name == CONSUMPTION_MIGRATION
    )
    apply_migrations(
        db_path=db_path,
        busy_timeout_ms=BUSY_TIMEOUT_MS,
        migrations=tuple(
            migration
            for migration in migrations
            if migration.version < consumption_migration.version
        ),
    )
    with sqlite3.connect(db_path) as connection:
        _insert_user(connection)
        for index in range(1, 4):
            _insert_activity(
                connection,
                log_id=f"log-{index}",
                created_at=f"2026-03-24T00:0{index}:59Z",
            )
        connection.execute(
            """
            INSERT INTO fact_activity_checkpoints(
                user_id, last_activity_created_at, last_activity_log_id, updated_at
            ) VALUES (?, ?, ?, ?)
            """,
            (
                USER_ID,
                "2026-03-24T00:02:59Z",
                "log-2",
                "2026-03-24T00:10:00Z",
            ),
        )

    apply_migrations(
        db_path=db_path,
        busy_timeout_ms=BUSY_TIMEOUT_MS,
        migrations=(consumption_migration,),
    )

    with sqlite3.connect(db_path) as connection:
        consumed = connection.execute(
            """
            SELECT activity_log_id, fact_run_id
            FROM fact_activity_consumptions
            ORDER BY activity_log_id
            """
        ).fetchall()
        legacy_table = connection.execute(
            """
            SELECT 1 FROM sqlite_master
            WHERE type = 'table' AND name = 'fact_activity_checkpoints'
            """
        ).fetchone()
    assert consumed == [("log-1", None), ("log-2", None)]
    assert legacy_table is None


def _insert_user(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        INSERT INTO users(user_id, ui_language, created_at, updated_at)
        VALUES (?, 'ja', '2026-03-24T00:00:00Z', '2026-03-24T00:00:00Z')
        """,
        (USER_ID,),
    )


def _insert_activity(
    connection: sqlite3.Connection,
    *,
    log_id: str,
    created_at: str,
    status: str = "success",
    description: str = "activity",
) -> None:
    connection.execute(
        """
        INSERT INTO activity_logs(
            log_id, user_id, period_start, period_end, description, status,
            prompt_name, prompt_version, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, 'activity', '1.0', ?, ?)
        """,
        (
            log_id,
            USER_ID,
            created_at,
            created_at,
            description,
            status,
            created_at,
            created_at,
        ),
    )
