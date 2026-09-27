"""Seed the `activity_logs` rows the short Insight run commits.

The short Insight run is the only writer of `activity_logs`, and it writes the
row and its inline memory document in one transaction. A test that needs a
stored activity log writes the same pair.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from pantaray_agents.agents.insight_agent.agent import InsightAgent
from pantaray_agents.local_runtime.memory_catalog.domain_registration import (
    register_inline_domain_memory,
)
from pantaray_agents.local_runtime.storage.migrations.connection import (
    configure_connection,
)
from pantaray_agents.local_runtime.storage.transactions import immediate_transaction
from pantaray_agents.local_runtime.storage.users import ensure_user_row


def seed_activity_log(
    db_path: Path | str,
    *,
    log_id: str,
    user_id: str,
    period_start: str,
    period_end: str,
    description: str = "desc",
    busy_timeout_ms: int = 1_000,
) -> None:
    with sqlite3.connect(str(db_path)) as connection:
        configure_connection(connection, busy_timeout_ms)
        with immediate_transaction(connection):
            ensure_user_row(connection, user_id=user_id, timestamp=period_end)
            connection.execute(
                """
                INSERT INTO activity_logs(
                    log_id, user_id, period_start, period_end, description,
                    status, prompt_name, prompt_version, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, 'success', ?, ?, ?, ?)
                """,
                (
                    log_id,
                    user_id,
                    period_start,
                    period_end,
                    description,
                    InsightAgent.PROMPT_NAME,
                    InsightAgent.PROMPT_VERSION,
                    period_end,
                    period_end,
                ),
            )
            register_inline_domain_memory(
                connection=connection,
                user_id=user_id,
                source="activity_log",
                source_record_id=log_id,
                content=description,
            )
