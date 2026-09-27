from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from pantaray_agents.local_runtime.runtime.reaper import run_local_periodic_reaper_once
from pantaray_agents.local_runtime.runtime.runtime_lock_coordinator import (
    reconcile_runtime_lock_resources_for_periodic_reaper,
)
from pantaray_agents.local_runtime.storage.migrations import (
    load_default_migrations,
)

from .migrated_db import prepare_test_database


def test_run_local_periodic_reaper_once_records_runtime_recovery_run(
    monkeypatch,
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "runtime.db"
    prepare_test_database(
        db_path=db_path,
        busy_timeout_ms=1_000,
        migrations=load_default_migrations(),
    )
    monkeypatch.setattr(
        "pantaray_agents.local_runtime.runtime.reaper.reconcile_runtime_lock_resources_for_periodic_reaper",
        lambda **_: 2,
    )
    monkeypatch.setattr(
        "pantaray_agents.local_runtime.runtime.reaper.reconcile_tool_runtime_resources_for_periodic_reaper",
        lambda **_: 3,
    )

    recovered_count = run_local_periodic_reaper_once(
        db_path=db_path,
        busy_timeout_ms=1_000,
    )

    assert recovered_count == 5
    with sqlite3.connect(db_path) as connection:
        run_row = connection.execute(
            """
            SELECT status, note
            FROM runtime_recovery_runs
            ORDER BY started_at DESC
            LIMIT 1
            """
        ).fetchone()

    assert run_row == (
        "completed",
        "periodic deterministic recovery checkpoint: recovered_runtime_locks=2; recovered_tool_resources=3",
    )


def test_periodic_reaper_cleans_stale_runtime_lock_resource(tmp_path: Path) -> None:
    db_path = tmp_path / "runtime.db"
    prepare_test_database(
        db_path=db_path,
        busy_timeout_ms=1_000,
        migrations=load_default_migrations(),
    )
    lock_path = db_path.parent / f"{db_path.name}.runtime.lock"
    lock_path.write_text(
        json.dumps(
            {
                "owner_pid": 999999,
                "lock_id": "stale-runtime-lock",
                "acquired_at": "2026-03-23T00:00:00Z",
            },
            ensure_ascii=False,
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    with sqlite3.connect(db_path) as connection:
        with connection:
            connection.execute(
                """
                INSERT INTO runtime_lock_resources(
                    resource_id,
                    lock_path,
                    lock_id,
                    owner_pid,
                    status,
                    created_at,
                    updated_at,
                    cleaned_at,
                    cleanup_error,
                    cleanup_attempts
                ) VALUES (?, ?, ?, ?, 'active', ?, ?, NULL, NULL, 0)
                """,
                (
                    "runtime-lock-resource-1",
                    str(lock_path),
                    "stale-runtime-lock",
                    999999,
                    "2026-03-23T00:00:00Z",
                    "2026-03-23T00:00:00Z",
                ),
            )

    recovered_count = reconcile_runtime_lock_resources_for_periodic_reaper(
        db_path=db_path,
        busy_timeout_ms=1_000,
    )

    assert recovered_count == 1
    assert not lock_path.exists()
    with sqlite3.connect(db_path) as connection:
        resource_row = connection.execute(
            """
            SELECT status
            FROM runtime_lock_resources
            WHERE resource_id = 'runtime-lock-resource-1'
            """
        ).fetchone()
        event_row = connection.execute(
            """
            SELECT event_type
            FROM runtime_lock_events
            WHERE resource_id = 'runtime-lock-resource-1'
            ORDER BY created_at DESC
            LIMIT 1
            """
        ).fetchone()

    assert resource_row == ("cleaned",)
    assert event_row == ("periodic_runtime_lock_completed",)
