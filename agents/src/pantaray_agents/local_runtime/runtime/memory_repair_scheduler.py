from __future__ import annotations

import logging
from pathlib import Path
from typing import Final

from ..memory_catalog.reconciler import reconcile_memory_catalog

logger = logging.getLogger(__name__)

MEMORY_REPAIR_PERIODIC_INTERVAL_SECONDS: Final[float] = 60.0
# The durable scan cursor lets repeated bounded runs eventually inspect every node.
MEMORY_REPAIR_PERIODIC_SCAN_LIMIT: Final[int] = 50


def run_memory_catalog_repair_once(
    *,
    db_path: Path,
    busy_timeout_ms: int,
    artifact_root: Path,
) -> None:
    enqueued, completed = reconcile_memory_catalog(
        db_path=db_path,
        busy_timeout_ms=busy_timeout_ms,
        artifact_root=artifact_root,
        scan_limit=MEMORY_REPAIR_PERIODIC_SCAN_LIMIT,
    )
    if completed > 0:
        logger.info(
            "Periodic memory catalog repair completed: "
            "memory_repairs_enqueued=%s memory_repairs_completed=%s",
            enqueued,
            completed,
        )


__all__ = [
    "MEMORY_REPAIR_PERIODIC_INTERVAL_SECONDS",
    "MEMORY_REPAIR_PERIODIC_SCAN_LIMIT",
    "run_memory_catalog_repair_once",
]
