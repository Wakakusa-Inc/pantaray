from __future__ import annotations

import sqlite3
from datetime import datetime

from .domain_registration import register_inline_domain_memory
from .models import MemoryRevision


def register_source_records_memory(
    *, connection: sqlite3.Connection, user_id: str, run_id: str
) -> MemoryRevision | None:
    """Publish one search projection from persisted evidence in the caller's tx."""
    connection.row_factory = sqlite3.Row
    rows = connection.execute(
        """SELECT record_id, event_id, observed_at, source, speaker, shown_time, quote
           FROM source_records WHERE user_id = ? AND run_id = ?
           ORDER BY observed_at, record_id""",
        (user_id, run_id),
    ).fetchall()
    if not rows:
        return None
    sections: list[str] = []
    for row in rows:
        speaker = f"Speaker: {_literal(row['speaker'])}; " if row["speaker"] else ""
        shown_time = (
            f"Shown time: {_literal(row['shown_time'])}; " if row["shown_time"] else ""
        )
        sections.append(
            f"## {_literal(row['source'])}\n\n"
            f"Text: {_literal(row['quote'])}\n"
            f"{speaker}{shown_time}"
            f"Observed: {_literal(row['observed_at'])}; "
            f"event_id: {_literal(row['event_id'])}; "
            f"record_id: {_literal(row['record_id'])}"
        )
    revision = register_inline_domain_memory(
        connection=connection,
        user_id=user_id,
        source="source_records",
        source_record_id=run_id,
        content="\n\n".join(sections) + "\n",
    )
    # Backfilled evidence must rank by observation, not the migration's wall clock.
    observed_at = max(
        (str(row["observed_at"]) for row in rows), key=datetime.fromisoformat
    )
    connection.execute(
        """UPDATE memory_nodes SET created_at = ?, updated_at = ?
           WHERE user_id = ? AND node_id = ?""",
        (observed_at, observed_at, user_id, revision.node_id),
    )
    return revision


def _literal(text: str) -> str:
    # Keep each quote in its source's paragraph. Screen text is evidence, never
    # authored headings or semantic links; the original bytes remain in the table.
    return " ".join(text.splitlines()).replace("[[ref:", r"[\[ref:")
