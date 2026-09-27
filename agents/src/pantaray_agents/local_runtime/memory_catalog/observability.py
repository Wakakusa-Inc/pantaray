from __future__ import annotations

import logging
import sqlite3
import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Literal

from prometheus_client import Counter, Gauge, Histogram

from pantaray_agents.local_runtime.storage.transactions import register_after_commit

from .errors import MemoryLinkValidationError, MemoryPublicationConflictError

MemoryCatalogEvent = Literal[
    "memory_link_created",
    "memory_link_removed",
    "memory_link_validation_failed",
    "memory_link_resolution_failed",
    "memory_revision_activated",
    "memory_revision_conflict",
    "memory_node_tombstoned",
    "memory_user_erasure_started",
    "memory_user_erasure_completed",
    "memory_user_erasure_failed",
    "memory_artifact_deletion_retried",
    "memory_artifact_deletion_failed",
    "memory_link_repair_enqueued",
    "memory_link_repaired",
    "memory_link_repair_failed",
]

logger = logging.getLogger("pantaray.memory_catalog")

MEMORY_CATALOG_EVENTS = Counter(
    "memory_catalog_events_total",
    "Memory Catalog state transitions grouped by event type",
    ("event",),
)
MEMORY_PUBLICATION_DURATION = Histogram(
    "memory_catalog_publication_duration_seconds",
    "Memory Catalog publication latency grouped by result",
    ("result",),
    buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5),
)
MEMORY_PREPARE_INTENTS = Gauge(
    "memory_catalog_prepare_intents",
    "Durable Memory Catalog artifact prepare intents",
)
MEMORY_REPAIR_BACKLOG = Gauge(
    "memory_catalog_repair_backlog",
    "Pending Memory Catalog repair jobs",
)
MEMORY_USER_ERASURE_JOBS = Gauge(
    "memory_catalog_user_erasure_jobs",
    "Pending Memory Catalog user erasure jobs grouped by state",
    ("state",),
)

_FAILURE_EVENTS: frozenset[MemoryCatalogEvent] = frozenset(
    {
        "memory_link_validation_failed",
        "memory_link_resolution_failed",
        "memory_revision_conflict",
        "memory_user_erasure_failed",
        "memory_artifact_deletion_failed",
        "memory_link_repair_failed",
    }
)
_ERASURE_STATES = ("planned", "quarantined", "database_detached")


def emit_memory_catalog_event(
    event: MemoryCatalogEvent,
    *,
    count: int = 1,
    user_id: str | None = None,
    node_id: str | None = None,
    revision_id: str | None = None,
    fragment_id: str | None = None,
    run_id: str | None = None,
    deletion_id: str | None = None,
    fault_code: str | None = None,
) -> None:
    if count <= 0:
        return
    MEMORY_CATALOG_EVENTS.labels(event=event).inc(count)
    fields: dict[str, str | int] = {"event_type": event, "event_count": count}
    for key, value in (
        ("user_id", user_id),
        ("node_id", node_id),
        ("revision_id", revision_id),
        ("fragment_id", fragment_id),
        ("run_id", run_id),
        ("deletion_id", deletion_id),
        ("fault_code", fault_code),
    ):
        if value is not None:
            fields[key] = value
    level = logging.WARNING if event in _FAILURE_EVENTS else logging.INFO
    logger.log(level, event, extra=fields)


def observe_publication_duration(
    *, result: Literal["success", "conflict", "error"], seconds: float
) -> None:
    MEMORY_PUBLICATION_DURATION.labels(result=result).observe(max(0.0, seconds))


@contextmanager
def observe_memory_publication(
    *,
    connection: sqlite3.Connection,
    user_id: str,
    node_id: str,
    revision_id: str,
    run_id: str,
    link_states: tuple[str, ...],
) -> Iterator[None]:
    started = time.perf_counter()
    duration_recorded = False
    success_scheduled = False
    try:
        yield
    except MemoryLinkValidationError as exc:
        observe_publication_duration(
            result="error", seconds=time.perf_counter() - started
        )
        emit_memory_catalog_event(
            "memory_link_validation_failed",
            user_id=user_id,
            node_id=node_id,
            revision_id=revision_id,
            run_id=run_id,
            fault_code=type(exc).__name__,
        )
        duration_recorded = True
        raise
    except MemoryPublicationConflictError as exc:
        observe_publication_duration(
            result="conflict", seconds=time.perf_counter() - started
        )
        emit_memory_catalog_event(
            "memory_revision_conflict",
            user_id=user_id,
            node_id=node_id,
            revision_id=revision_id,
            run_id=run_id,
            fault_code=type(exc).__name__,
        )
        duration_recorded = True
        raise
    else:

        def emit_committed_events() -> None:
            observe_publication_duration(
                result="success", seconds=time.perf_counter() - started
            )
            emit_memory_catalog_event(
                "memory_revision_activated",
                user_id=user_id,
                node_id=node_id,
                revision_id=revision_id,
                run_id=run_id,
            )
            transitions: tuple[tuple[MemoryCatalogEvent, str], ...] = (
                ("memory_link_created", "pending"),
                ("memory_link_removed", "removed"),
            )
            for event, state in transitions:
                emit_memory_catalog_event(
                    event,
                    count=link_states.count(state),
                    user_id=user_id,
                    node_id=node_id,
                    revision_id=revision_id,
                    run_id=run_id,
                )

        register_after_commit(connection=connection, callback=emit_committed_events)
        success_scheduled = True
    finally:
        if not duration_recorded and not success_scheduled:
            observe_publication_duration(
                result="error", seconds=time.perf_counter() - started
            )


def refresh_memory_catalog_backlog_metrics(*, connection: sqlite3.Connection) -> None:
    intent_count = int(
        connection.execute("SELECT COUNT(*) FROM memory_revision_intents").fetchone()[0]
    )
    repair_count = int(
        connection.execute(
            "SELECT COUNT(*) FROM memory_repair_queue WHERE state = 'pending'"
        ).fetchone()[0]
    )
    MEMORY_PREPARE_INTENTS.set(intent_count)
    MEMORY_REPAIR_BACKLOG.set(repair_count)
    rows = connection.execute(
        """
        SELECT state, COUNT(*) AS job_count
        FROM memory_artifact_deletions
        WHERE reason = 'user_erasure'
        GROUP BY state
        """
    ).fetchall()
    counts = {str(row["state"]): int(row["job_count"]) for row in rows}
    for state in _ERASURE_STATES:
        MEMORY_USER_ERASURE_JOBS.labels(state=state).set(counts.get(state, 0))


__all__ = [
    "emit_memory_catalog_event",
    "observe_memory_publication",
    "observe_publication_duration",
    "refresh_memory_catalog_backlog_metrics",
]
