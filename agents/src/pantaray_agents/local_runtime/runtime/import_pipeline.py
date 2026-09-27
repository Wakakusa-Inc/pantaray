from __future__ import annotations

from pathlib import Path

from pantaray_agents.local_runtime.storage.import_runs import (
    _finalize_import_run_row,
    _record_import_run_source_row,
    _start_import_run_row,
    get_import_run,
)
from pantaray_agents.local_runtime.storage.migrations import MigrationError

from .identity import current_owner_id, verify_current_owner


def start_local_import_run(
    *,
    db_path: Path,
    busy_timeout_ms: int,
    requested_by: str,
    force_reindex: bool,
) -> str:
    return _start_import_run_row(
        db_path=db_path,
        busy_timeout_ms=busy_timeout_ms,
        user_id=current_owner_id(),
        requested_by=requested_by,
        force_reindex=force_reindex,
    )


def record_local_import_run_source(
    *,
    db_path: Path,
    busy_timeout_ms: int,
    import_run_id: str,
    source_name: str,
    status: str,
    watermark_value: str | None,
    imported_count: int,
    skipped_count: int,
    artifact_repaired_count: int,
    started_at: str,
    completed_at: str | None,
    error_code: str | None,
    error_message: str | None,
) -> str:
    _require_import_run_owner_is_current(
        db_path=db_path,
        busy_timeout_ms=busy_timeout_ms,
        import_run_id=import_run_id,
    )
    return _record_import_run_source_row(
        db_path=db_path,
        busy_timeout_ms=busy_timeout_ms,
        import_run_id=import_run_id,
        source_name=source_name,
        status=status,
        watermark_value=watermark_value,
        imported_count=imported_count,
        skipped_count=skipped_count,
        artifact_repaired_count=artifact_repaired_count,
        started_at=started_at,
        completed_at=completed_at,
        error_code=error_code,
        error_message=error_message,
    )


def finalize_local_import_run(
    *,
    db_path: Path,
    busy_timeout_ms: int,
    import_run_id: str,
    status: str,
    error_code: str | None,
    error_message: str | None,
) -> None:
    _require_import_run_owner_is_current(
        db_path=db_path,
        busy_timeout_ms=busy_timeout_ms,
        import_run_id=import_run_id,
    )
    _finalize_import_run_row(
        db_path=db_path,
        busy_timeout_ms=busy_timeout_ms,
        import_run_id=import_run_id,
        status=status,
        error_code=error_code,
        error_message=error_message,
    )


def _require_import_run_owner_is_current(
    *,
    db_path: Path,
    busy_timeout_ms: int,
    import_run_id: str,
) -> str:
    import_run = get_import_run(
        db_path=db_path,
        busy_timeout_ms=busy_timeout_ms,
        import_run_id=import_run_id,
    )
    if import_run is None:
        raise MigrationError(f"import_run_id not found: {import_run_id}")
    verify_current_owner(import_run.user_id)
    return import_run.user_id


__all__ = [
    "finalize_local_import_run",
    "record_local_import_run_source",
    "start_local_import_run",
]
