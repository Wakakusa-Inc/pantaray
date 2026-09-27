from __future__ import annotations

import sqlite3

from .connection import add_column_if_missing, table_exists


def apply_activity_summary_fact_followup_migration(
    connection: sqlite3.Connection,
) -> None:
    if not table_exists(connection, table_name="activity_summaries"):
        return
    add_column_if_missing(
        connection=connection,
        table_name="activity_summaries",
        column_definition="fact_followup_fact_id TEXT",
    )
    add_column_if_missing(
        connection=connection,
        table_name="activity_summaries",
        column_definition="fact_followup_enqueued_at TEXT",
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_activity_summaries_fact_followup_fact_id
        ON activity_summaries(fact_followup_fact_id)
        """
    )
