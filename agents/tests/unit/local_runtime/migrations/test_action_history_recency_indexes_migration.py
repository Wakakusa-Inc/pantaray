from __future__ import annotations

import sqlite3
from pathlib import Path

from pantaray_agents.local_runtime.storage.migrations import (
    apply_migrations,
    load_default_migrations,
)
from pantaray_agents.local_runtime.storage.migrations.connection import (
    configure_connection,
)

from .support import _insert_user, _migrations_through

BUSY_TIMEOUT_MS = 1_000
V91_MIGRATION_NAME = "0091_action_conversation_query_indexes.sql"
V92_MIGRATION_NAME = "0092_action_history_recency_indexes.sql"
MICROSECOND_TIMESTAMP = "2026-08-30T00:00:00.123456Z"
MILLISECOND_TIMESTAMP = "2026-08-30T00:00:00.123Z"
INDEX_CASES = (
    (
        "idx_agent_actions_user_history_recency",
        "agent_actions",
        "action_id",
    ),
    (
        "idx_agent_suggestions_user_history_recency",
        "agent_suggestions",
        "suggestion_id",
    ),
)


def _seed_history_rows(connection: sqlite3.Connection, timestamp: str) -> None:
    _insert_user(connection, "user-1")
    connection.execute(
        """INSERT INTO agent_suggestions(
        suggestion_id,user_id,status,has_suggestion,interaction_contract,
        created_at,updated_at)
        VALUES ('suggestion-1','user-1','success',0,'message_only',?,?)""",
        (timestamp, timestamp),
    )
    connection.execute(
        """INSERT INTO agent_actions(
        action_id,user_id,initial_user_message_id,execution_target_json,status,
        final_output,prompt_name,prompt_version,created_at,updated_at)
        VALUES ('action-1','user-1','message-1','{"kind":"scratch"}',
                'processing','','action','1',?,?)""",
        (timestamp, timestamp),
    )


def test_v92_normalizes_recency_and_adds_keyset_indexes(tmp_path: Path) -> None:
    db_path = tmp_path / "runtime.db"
    migrations = load_default_migrations()
    through_v91 = _migrations_through(migrations, V91_MIGRATION_NAME)
    through_v92 = _migrations_through(migrations, V92_MIGRATION_NAME)
    apply_migrations(db_path, BUSY_TIMEOUT_MS, through_v91)
    with sqlite3.connect(db_path) as connection:
        with connection:
            _seed_history_rows(connection, MICROSECOND_TIMESTAMP)

    apply_migrations(db_path, BUSY_TIMEOUT_MS, through_v92)

    with sqlite3.connect(db_path) as connection:
        configure_connection(connection, BUSY_TIMEOUT_MS)
        timestamps = connection.execute(
            """SELECT created_at,updated_at FROM agent_actions
            UNION ALL
            SELECT created_at,updated_at FROM agent_suggestions"""
        ).fetchall()
        for index_name, table_name, stable_id in INDEX_CASES:
            key_columns = tuple(
                (str(row[2]), int(row[3]))
                for row in connection.execute(
                    f"PRAGMA index_xinfo('{index_name}')"
                ).fetchall()
                if row[5] == 1
            )
            plan = connection.execute(
                f"""EXPLAIN QUERY PLAN SELECT {stable_id} FROM {table_name}
                WHERE user_id=?
                  AND (updated_at<? OR (updated_at=? AND {stable_id}>?))
                ORDER BY updated_at DESC,{stable_id} LIMIT 21""",
                ("user-1", MILLISECOND_TIMESTAMP, MILLISECOND_TIMESTAMP, ""),
            ).fetchall()
            details = tuple(str(row[3]) for row in plan)

            assert key_columns == (
                ("user_id", 0),
                ("updated_at", 1),
                (stable_id, 0),
            )
            assert any(index_name in detail for detail in details)
            assert all("TEMP B-TREE" not in detail for detail in details)

    assert timestamps == [(MILLISECOND_TIMESTAMP, MILLISECOND_TIMESTAMP)] * 2
