from __future__ import annotations

import shutil
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from pantaray_agents.local_runtime.storage.transactions import immediate_transaction

from .connection import open_memory_catalog_connection

_CATALOG_TABLES: tuple[str, ...] = (
    "agent_experience_extraction_runs",
    "memory_links",
    "memory_evidence_edges",
    "memory_revision_parents",
    "memory_repair_queue",
    "memory_revision_intents",
    "memory_fragments",
    "memory_revisions",
    "memory_nodes",
    "memory_link_quarantine",
    "memory_artifact_deletions",
)


@dataclass(frozen=True, slots=True)
class PartialCatalogState:
    row_count: int
    artifacts_present: bool
    pending_user_erasure_count: int

    @property
    def exists(self) -> bool:
        return self.row_count > 0 or self.artifacts_present


def inspect_partial_catalog(
    *, connection: sqlite3.Connection, artifact_root: Path
) -> PartialCatalogState:
    row_count = sum(
        int(connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])
        for table in _CATALOG_TABLES
    )
    return PartialCatalogState(
        row_count=row_count,
        artifacts_present=(artifact_root / "memory_catalog").exists(),
        pending_user_erasure_count=int(
            connection.execute(
                """
                SELECT COUNT(*)
                FROM memory_artifact_deletions
                WHERE reason = 'user_erasure'
                """
            ).fetchone()[0]
        ),
    )


def reset_partial_catalog(
    *,
    db_path: Path,
    busy_timeout_ms: int,
    artifact_root: Path,
) -> None:
    with open_memory_catalog_connection(
        db_path=db_path, busy_timeout_ms=busy_timeout_ms
    ) as connection:
        with immediate_transaction(connection):
            for table in _CATALOG_TABLES:
                connection.execute(f'DELETE FROM "{table}"')
            connection.execute(
                """
                UPDATE memory_catalog_reconcile_state
                SET last_user_id = NULL, last_node_id = NULL,
                    updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
                WHERE singleton_id = 1
                """
            )
    catalog_root = artifact_root / "memory_catalog"
    if catalog_root.exists():
        shutil.rmtree(catalog_root)
