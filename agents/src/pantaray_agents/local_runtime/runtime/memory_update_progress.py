"""Durable per-category progress of one unified Memory agent run.

A unified run publishes one artifact revision per memory category, each in its
own transaction. A crash between two of those transactions must not republish a
category that already activated, so every activation records
``memory_category_published`` on the run's own process, inside the activation
transaction. The rerun of the same job reads those events before it prepares any
draft and skips the categories they name. ``memory_update_completed`` closes the
run and is what ``is_complete`` reads.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Final, cast

from pantaray_agents.local_runtime.memory_catalog.models import MemorySource
from pantaray_agents.local_runtime.storage.migrations import MigrationError

from .process_events import append_process_event_in_connection

MEMORY_CATEGORY_PUBLISHED_EVENT: Final[str] = "memory_category_published"
MEMORY_UPDATE_COMPLETED_EVENT: Final[str] = "memory_update_completed"
MEMORY_UPDATE_CATEGORIES: Final[tuple[MemorySource, ...]] = (
    "fact",
    "long_term_insight",
    "agent_experience",
)


def append_memory_category_published_in_connection(
    *,
    connection: sqlite3.Connection,
    process_id: str,
    source: MemorySource,
    revision_id: str,
    created_at: str,
) -> None:
    """Record one activated category inside its own activation transaction."""

    if source not in MEMORY_UPDATE_CATEGORIES:
        raise MigrationError("memory update category is invalid")
    if not revision_id.strip():
        raise MigrationError("published memory revision must be identified")
    append_process_event_in_connection(
        connection=connection,
        process_id=process_id,
        event_name=MEMORY_CATEGORY_PUBLISHED_EVENT,
        payload={"source": source, "revision_id": revision_id},
        created_at=created_at,
    )


def append_memory_update_completed_in_connection(
    *,
    connection: sqlite3.Connection,
    process_id: str,
    published_sources: tuple[MemorySource, ...],
    created_at: str,
) -> None:
    append_process_event_in_connection(
        connection=connection,
        process_id=process_id,
        event_name=MEMORY_UPDATE_COMPLETED_EVENT,
        payload={"published_sources": list(published_sources)},
        created_at=created_at,
    )


def load_published_memory_categories(
    *, connection: sqlite3.Connection, process_id: str
) -> frozenset[MemorySource]:
    rows = connection.execute(
        """
        SELECT payload_json FROM process_events
        WHERE process_id = ? AND event_name = ?
        """,
        (process_id, MEMORY_CATEGORY_PUBLISHED_EVENT),
    ).fetchall()
    return frozenset(_published_source(str(row["payload_json"])) for row in rows)


def memory_update_is_complete(
    *, connection: sqlite3.Connection, process_id: str
) -> bool:
    row = connection.execute(
        """
        SELECT 1 FROM process_events
        WHERE process_id = ? AND event_name = ?
        LIMIT 1
        """,
        (process_id, MEMORY_UPDATE_COMPLETED_EVENT),
    ).fetchone()
    return row is not None


def _published_source(payload_json: str) -> MemorySource:
    payload = json.loads(payload_json)
    if not isinstance(payload, dict):
        raise MigrationError("memory category event payload must be an object")
    source = payload.get("source")
    if source not in MEMORY_UPDATE_CATEGORIES:
        raise MigrationError("memory category event source is invalid")
    return cast(MemorySource, source)


__all__ = [
    "MEMORY_CATEGORY_PUBLISHED_EVENT",
    "MEMORY_UPDATE_CATEGORIES",
    "MEMORY_UPDATE_COMPLETED_EVENT",
    "append_memory_category_published_in_connection",
    "append_memory_update_completed_in_connection",
    "load_published_memory_categories",
    "memory_update_is_complete",
]
