import json
import sqlite3
from contextlib import closing

import pytest

from pantaray_agents.local_runtime.memory_catalog.domain_registration import (
    register_inline_domain_memory,
)
from pantaray_agents.local_runtime.storage.migrations import (
    apply_migrations,
    load_default_migrations,
)
from pantaray_agents.local_runtime.storage.migrations.connection import (
    configure_connection,
)
from pantaray_agents.local_runtime.storage.transactions import immediate_transaction

from .support import _migrations_through

RETIRED_TABLES = (
    "context_work_heads",
    "context_work_revisions",
    "context_batch_activities",
    "context_batches",
)
SOURCE_TABLES = ("context_sources", "context_source_receipts", "context_streams")


@pytest.mark.parametrize("populated", [False, True])
def test_drop_work_state_preserves_source_and_catalog_data(tmp_path, populated):
    path = tmp_path / "runtime.sqlite3"
    migrations = load_default_migrations()
    apply_migrations(
        path, 1000, _migrations_through(migrations, "0096_zanei_context.sql")
    )
    with closing(sqlite3.connect(path)) as connection:
        configure_connection(connection, 1000)
        connection.execute(
            "INSERT INTO users VALUES ('user', 'ja', NULL, 'now', 'now')"
        )
        connection.execute("INSERT INTO context_sources VALUES ('user', '{}')")
        connection.execute(
            "INSERT INTO context_source_receipts VALUES ('user', 'request', '{}', '{}')"
        )
        binding = json.dumps({"user_id": "user"})
        connection.execute(
            "INSERT INTO context_streams VALUES ('user', ?, 'cursor')", (binding,)
        )
        connection.commit()
        with immediate_transaction(connection):
            activity = register_inline_domain_memory(
                connection=connection,
                user_id="user",
                source="activity_log",
                source_record_id="activity",
                content="Existing Activity memory",
            )
            insight = register_inline_domain_memory(
                connection=connection,
                user_id="user",
                source="short_term_insight",
                source_record_id="insight",
                content="Existing Insight memory",
            )
        if populated:
            outcome = json.dumps(
                {"coverage": {"batch_id": "batch", "binding": {"user_id": "user"}}}
            )
            record = json.dumps(
                {
                    "context": {
                        "user_id": "user",
                        "work": {"work_id": "work", "revision": 1},
                    }
                }
            )
            connection.execute(
                "INSERT INTO context_batches VALUES ('user', 'batch', ?, ?)",
                (binding, outcome),
            )
            connection.execute(
                "INSERT INTO context_batch_activities VALUES ('user', 'batch', ?, ?, '{}')",
                (activity.node_id, activity.revision_id),
            )
            connection.execute(
                "INSERT INTO context_work_revisions VALUES ('user', 'work', 1, 'batch', ?, ?, ?)",
                (insight.node_id, insight.revision_id, record),
            )
            connection.execute(
                "INSERT INTO context_work_heads VALUES ('user', 'work', 1)"
            )
            connection.commit()
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        preserved_before = {
            table: [tuple(row) for row in connection.execute(f"SELECT * FROM {table}")]
            for table in (
                *SOURCE_TABLES,
                "memory_nodes",
                "memory_revisions",
                "memory_fragments",
            )
        }

    upgraded = _migrations_through(migrations, "0097_drop_structured_work_state.sql")
    for _ in range(2):
        apply_migrations(path, 1000, upgraded)
    with closing(sqlite3.connect(path)) as connection:
        configure_connection(connection, 1000)
        assert connection.execute(
            "SELECT current_version FROM schema_versions WHERE component='local_runtime'"
        ).fetchone() == (97,)
        for table in RETIRED_TABLES:
            assert (
                connection.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                    (table,),
                ).fetchone()
                is None
            )
        for table, rows in preserved_before.items():
            assert [
                tuple(row) for row in connection.execute(f"SELECT * FROM {table}")
            ] == rows
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)
