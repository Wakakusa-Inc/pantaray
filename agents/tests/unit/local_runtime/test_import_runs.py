from __future__ import annotations

from pathlib import Path

import pytest

from pantaray_agents.local_runtime.storage.import_runs import (
    _finalize_import_run_row,
    _record_import_run_source_row,
    _start_import_run_row,
    get_import_run,
    list_import_run_sources,
)
from pantaray_agents.local_runtime.storage.migrations import (
    MigrationError,
    load_default_migrations,
)

from .migrated_db import prepare_test_database


def test_import_run_lifecycle_roundtrip(tmp_path: Path) -> None:
    db_path = tmp_path / "runtime.db"
    prepare_test_database(
        db_path=db_path,
        busy_timeout_ms=1_000,
        migrations=load_default_migrations(),
    )

    import_run_id = _start_import_run_row(
        db_path=db_path,
        busy_timeout_ms=1_000,
        user_id="user-1",
        requested_by="user",
        force_reindex=False,
    )
    source_id = _record_import_run_source_row(
        db_path=db_path,
        busy_timeout_ms=1_000,
        import_run_id=import_run_id,
        source_name="supabase",
        status="completed",
        watermark_value="snapshot-1",
        imported_count=10,
        skipped_count=0,
        artifact_repaired_count=0,
        started_at="2026-03-22T00:00:00Z",
        completed_at="2026-03-22T00:10:00Z",
        error_code=None,
        error_message=None,
    )

    assert source_id != ""

    _finalize_import_run_row(
        db_path=db_path,
        busy_timeout_ms=1_000,
        import_run_id=import_run_id,
        status="completed",
        error_code=None,
        error_message=None,
    )
    run = get_import_run(
        db_path=db_path,
        busy_timeout_ms=1_000,
        import_run_id=import_run_id,
    )

    assert run is not None
    assert run.status == "completed"
    assert run.user_id == "user-1"
    assert run.completed_at is not None
    source_rows = list_import_run_sources(
        db_path=db_path,
        busy_timeout_ms=1_000,
        import_run_id=import_run_id,
    )
    assert len(source_rows) == 1
    assert source_rows[0].status == "completed"


def test_finalize_import_run_rejects_running_status(tmp_path: Path) -> None:
    db_path = tmp_path / "runtime.db"
    prepare_test_database(
        db_path=db_path,
        busy_timeout_ms=1_000,
        migrations=load_default_migrations(),
    )
    import_run_id = _start_import_run_row(
        db_path=db_path,
        busy_timeout_ms=1_000,
        user_id="user-2",
        requested_by="user",
        force_reindex=False,
    )

    with pytest.raises(MigrationError, match="does not accept running status"):
        _finalize_import_run_row(
            db_path=db_path,
            busy_timeout_ms=1_000,
            import_run_id=import_run_id,
            status="running",
            error_code=None,
            error_message=None,
        )


def test_record_import_run_source_rejects_negative_count(tmp_path: Path) -> None:
    db_path = tmp_path / "runtime.db"
    prepare_test_database(
        db_path=db_path,
        busy_timeout_ms=1_000,
        migrations=load_default_migrations(),
    )
    import_run_id = _start_import_run_row(
        db_path=db_path,
        busy_timeout_ms=1_000,
        user_id="user-3",
        requested_by="user",
        force_reindex=False,
    )

    with pytest.raises(MigrationError, match="imported_count"):
        _record_import_run_source_row(
            db_path=db_path,
            busy_timeout_ms=1_000,
            import_run_id=import_run_id,
            source_name="supabase",
            status="completed",
            watermark_value="snapshot-2",
            imported_count=-1,
            skipped_count=0,
            artifact_repaired_count=0,
            started_at="2026-03-22T00:00:00Z",
            completed_at=None,
            error_code=None,
            error_message=None,
        )


def test_record_import_run_source_rejects_invalid_status(tmp_path: Path) -> None:
    db_path = tmp_path / "runtime.db"
    prepare_test_database(
        db_path=db_path,
        busy_timeout_ms=1_000,
        migrations=load_default_migrations(),
    )
    import_run_id = _start_import_run_row(
        db_path=db_path,
        busy_timeout_ms=1_000,
        user_id="user-4",
        requested_by="user",
        force_reindex=False,
    )

    with pytest.raises(MigrationError, match="import source status"):
        _record_import_run_source_row(
            db_path=db_path,
            busy_timeout_ms=1_000,
            import_run_id=import_run_id,
            source_name="supabase",
            status="processing",
            watermark_value="snapshot-3",
            imported_count=5,
            skipped_count=0,
            artifact_repaired_count=0,
            started_at="2026-03-22T00:00:00Z",
            completed_at=None,
            error_code=None,
            error_message=None,
        )
