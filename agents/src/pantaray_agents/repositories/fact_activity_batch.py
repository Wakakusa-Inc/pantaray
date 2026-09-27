from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from pantaray_agents.schema.repositories.repository import JSONValue


@dataclass(frozen=True, slots=True)
class FactActivityBatch[ActivityRow]:
    initial_rows: tuple[ActivityRow, ...]
    deferred_rows: tuple[ActivityRow, ...]


def split_fact_activity_batch[ActivityRow: Mapping[str, JSONValue]](
    *,
    rows: Sequence[ActivityRow],
    target_total_chars: int,
) -> FactActivityBatch[ActivityRow]:
    """Split oldest-first evidence without dropping overflow records."""
    if target_total_chars < 1:
        raise ValueError("target_total_chars must be positive")

    initial_count = 0
    total_chars = 0
    for row in rows:
        description_chars = len(str(row.get("description") or ""))
        if initial_count and total_chars + description_chars > target_total_chars:
            break
        initial_count += 1
        total_chars += description_chars
    return FactActivityBatch(
        initial_rows=tuple(rows[:initial_count]),
        deferred_rows=tuple(rows[initial_count:]),
    )
