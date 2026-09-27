from __future__ import annotations

from pathlib import Path

from ..storage.migrations import record_runtime_recovery_run
from ..tooling.resources.resource_recovery import (
    reconcile_tool_runtime_resources_for_periodic_reaper,
)
from .runtime_lock_coordinator import (
    reconcile_runtime_lock_resources_for_periodic_reaper,
)


def run_local_periodic_reaper_once(
    *,
    db_path: Path,
    busy_timeout_ms: int,
) -> int:
    recovered_runtime_lock_count = reconcile_runtime_lock_resources_for_periodic_reaper(
        db_path=db_path,
        busy_timeout_ms=busy_timeout_ms,
    )
    recovered_tool_resource_count = (
        reconcile_tool_runtime_resources_for_periodic_reaper(
            db_path=db_path,
            busy_timeout_ms=busy_timeout_ms,
        )
    )
    recovery_note = (
        "periodic deterministic recovery checkpoint: "
        f"recovered_runtime_locks={recovered_runtime_lock_count}; "
        f"recovered_tool_resources={recovered_tool_resource_count}"
    )
    record_runtime_recovery_run(
        db_path=db_path,
        busy_timeout_ms=busy_timeout_ms,
        note=recovery_note,
    )
    return recovered_runtime_lock_count + recovered_tool_resource_count


__all__ = ["run_local_periodic_reaper_once"]
