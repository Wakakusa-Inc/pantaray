from __future__ import annotations

import sqlite3

from .sql_script import execute_sql_statements


def apply_source_records_memory_migration(
    connection: sqlite3.Connection, *, migration_statements: tuple[str, ...]
) -> None:
    execute_sql_statements(connection, migration_statements)
    # Catalog imports depend on initialized migration modules.
    from pantaray_agents.local_runtime.memory_catalog.source_records import (
        register_source_records_memory,
    )

    connection.row_factory = sqlite3.Row
    runs = connection.execute(
        "SELECT DISTINCT user_id, run_id FROM source_records ORDER BY user_id, run_id"
    ).fetchall()
    for run in runs:
        register_source_records_memory(
            connection=connection,
            user_id=str(run["user_id"]),
            run_id=str(run["run_id"]),
        )
