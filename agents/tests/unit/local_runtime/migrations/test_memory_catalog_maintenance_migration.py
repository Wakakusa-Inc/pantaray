from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from pantaray_agents.local_runtime.memory_catalog.domain_registration import (
    register_inline_domain_memory,
)
from pantaray_agents.local_runtime.storage.migrations import (
    MigrationError,
    verify_database_integrity,
)
from pantaray_agents.local_runtime.storage.migrations import runner as migration_runner
from pantaray_agents.local_runtime.storage.transactions import immediate_transaction

from .support import (
    _configure_connection,
    _insert_user,
    _migrations_through,
    apply_migrations,
    load_default_migrations,
)

PREVIOUS_MIGRATION = "0063_optional_insight_update_provenance.sql"
BUSY_TIMEOUT_MS = 1_000


def test_memory_catalog_maintenance_migration_preserves_pending_jobs(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "runtime.db"
    migrations = load_default_migrations()
    apply_migrations(
        db_path=db_path,
        busy_timeout_ms=BUSY_TIMEOUT_MS,
        migrations=_migrations_through(migrations, PREVIOUS_MIGRATION),
    )
    with sqlite3.connect(db_path) as connection:
        _configure_connection(connection, busy_timeout_ms=BUSY_TIMEOUT_MS)
        connection.row_factory = sqlite3.Row
        with immediate_transaction(connection):
            _insert_user(connection, "user-1")
            revision = register_inline_domain_memory(
                connection=connection,
                user_id="user-1",
                source="activity_log",
                source_record_id="migration-log",
                content="migration content",
            )
            node = connection.execute(
                """
                SELECT node_id FROM memory_nodes
                WHERE user_id = 'user-1' AND source_record_id = 'migration-log'
                """
            ).fetchone()
            assert node is not None
            connection.execute(
                """
                INSERT INTO memory_repair_queue(
                    user_id, node_id, detected_revision_id, reason,
                    state, created_at
                ) VALUES (?, ?, ?, 'revision_integrity', 'pending', ?)
                """,
                (
                    "user-1",
                    str(node["node_id"]),
                    revision.revision_id,
                    "2026-07-20T00:00:00Z",
                ),
            )

    apply_migrations(
        db_path=db_path,
        busy_timeout_ms=BUSY_TIMEOUT_MS,
        migrations=migrations,
    )
    verify_database_integrity(db_path=db_path, busy_timeout_ms=BUSY_TIMEOUT_MS)

    with sqlite3.connect(db_path) as connection:
        connection.row_factory = sqlite3.Row
        row = connection.execute(
            """
            SELECT reason, state, attempt_count, next_attempt_at, last_error_code
            FROM memory_repair_queue
            """
        ).fetchone()
        assert row is not None
        connection.execute(
            """
            INSERT INTO memory_repair_queue(
                user_id, node_id, detected_revision_id, reason, state,
                attempt_count, next_attempt_at, created_at
            ) VALUES (?, ?, ?, 'link_manifest_mismatch', 'pending', 0, ?, ?)
            """,
            (
                "user-1",
                str(node["node_id"]),
                revision.revision_id,
                "2026-07-20T00:00:00Z",
                "2026-07-20T00:00:00Z",
            ),
        )
        reason_count = connection.execute(
            "SELECT COUNT(*) FROM memory_repair_queue"
        ).fetchone()[0]
        cursor = connection.execute(
            """
            SELECT last_user_id, last_node_id
            FROM memory_catalog_reconcile_state WHERE singleton_id = 1
            """
        ).fetchone()

    assert dict(row) == {
        "reason": "revision_integrity",
        "state": "pending",
        "attempt_count": 0,
        "next_attempt_at": "2026-07-20T00:00:00Z",
        "last_error_code": None,
    }
    assert reason_count == 2
    assert cursor is not None
    assert tuple(cursor) == (None, None)


def test_memory_catalog_maintenance_rolls_back_an_interrupted_script(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "runtime.db"
    migrations = load_default_migrations()
    apply_migrations(
        db_path=db_path,
        busy_timeout_ms=BUSY_TIMEOUT_MS,
        migrations=_migrations_through(migrations, PREVIOUS_MIGRATION),
    )
    migration = next(item for item in migrations if item.version == 64)
    original_execute = migration_runner.execute_sql_statements

    def interrupt_after_rename(
        connection: sqlite3.Connection,
        statements: tuple[str, ...],
    ) -> None:
        connection.execute(statements[0])
        raise RuntimeError("simulated interruption")

    monkeypatch.setattr(
        migration_runner,
        "execute_sql_statements",
        interrupt_after_rename,
    )
    with pytest.raises(MigrationError):
        apply_migrations(
            db_path=db_path,
            busy_timeout_ms=BUSY_TIMEOUT_MS,
            migrations=(migration,),
        )

    with sqlite3.connect(db_path) as connection:
        table_names = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        schema_version = connection.execute(
            "SELECT current_version FROM schema_versions WHERE component = 'local_runtime'"
        ).fetchone()
    assert "memory_repair_queue" in table_names
    assert "memory_repair_queue_v0063" not in table_names
    assert schema_version == (63,)

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
