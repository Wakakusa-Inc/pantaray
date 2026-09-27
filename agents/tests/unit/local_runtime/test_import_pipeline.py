from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from pantaray_agents.local_runtime.runtime.identity import (
    OwnerMismatchError,
    register_logged_out_owner,
    reset_logged_out_owner,
)
from pantaray_agents.local_runtime.runtime.import_pipeline import (
    finalize_local_import_run,
    record_local_import_run_source,
    start_local_import_run,
)
from pantaray_agents.local_runtime.runtime.session_store import (
    import_desktop_session,
    reset_desktop_session_store,
)
from pantaray_agents.local_runtime.storage.import_runs import get_import_run
from pantaray_agents.local_runtime.storage.migrations.specs import (
    load_default_migrations,
)

from .migrated_db import prepare_test_database


def _apply_schema(db_path: Path) -> None:
    prepare_test_database(
        db_path=db_path,
        busy_timeout_ms=1_000,
        migrations=load_default_migrations(),
    )


def _future_expiry() -> str:
    return (datetime.now(UTC) + timedelta(hours=1)).isoformat()


def _activate_user(db_path: Path, *, user_id: str, session_version: str) -> None:
    import_desktop_session(
        db_path=db_path,
        busy_timeout_ms=1_000,
        user_id=user_id,
        desktop_access_token="token",
        expires_at=_future_expiry(),
        session_version=session_version,
    )


@pytest.fixture(autouse=True)
def reset_owner_state() -> None:
    reset_desktop_session_store()
    register_logged_out_owner("local-owner")
    yield
    reset_desktop_session_store()
    reset_logged_out_owner()


def test_start_local_import_run_belongs_to_the_logged_out_owner(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "runtime.db"
    _apply_schema(db_path)

    import_run_id = start_local_import_run(
        db_path=db_path,
        busy_timeout_ms=1_000,
        requested_by="user",
        force_reindex=False,
    )
    import_run = get_import_run(
        db_path=db_path,
        busy_timeout_ms=1_000,
        import_run_id=import_run_id,
    )

    assert import_run is not None
    assert import_run.user_id == "local-owner"


def test_start_local_import_run_uses_active_user_id(tmp_path: Path) -> None:
    db_path = tmp_path / "runtime.db"
    _apply_schema(db_path)
    _activate_user(db_path, user_id="user-1", session_version="1")

    import_run_id = start_local_import_run(
        db_path=db_path,
        busy_timeout_ms=1_000,
        requested_by="user",
        force_reindex=False,
    )
    import_run = get_import_run(
        db_path=db_path,
        busy_timeout_ms=1_000,
        import_run_id=import_run_id,
    )

    assert import_run is not None
    assert import_run.user_id == "user-1"


def test_finalize_local_import_run_requires_matching_owner_user(tmp_path: Path) -> None:
    db_path = tmp_path / "runtime.db"
    _apply_schema(db_path)
    _activate_user(db_path, user_id="user-1", session_version="1")
    import_run_id = start_local_import_run(
        db_path=db_path,
        busy_timeout_ms=1_000,
        requested_by="user",
        force_reindex=False,
    )

    _activate_user(db_path, user_id="user-2", session_version="2")

    with pytest.raises(
        OwnerMismatchError,
        match="does not match the current owner",
    ):
        finalize_local_import_run(
            db_path=db_path,
            busy_timeout_ms=1_000,
            import_run_id=import_run_id,
            status="completed",
            error_code=None,
            error_message=None,
        )


def test_record_local_import_run_source_requires_matching_owner_user(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "runtime.db"
    _apply_schema(db_path)
    _activate_user(db_path, user_id="user-1", session_version="1")
    import_run_id = start_local_import_run(
        db_path=db_path,
        busy_timeout_ms=1_000,
        requested_by="user",
        force_reindex=False,
    )

    _activate_user(db_path, user_id="user-2", session_version="2")

    with pytest.raises(
        OwnerMismatchError,
        match="does not match the current owner",
    ):
        record_local_import_run_source(
            db_path=db_path,
            busy_timeout_ms=1_000,
            import_run_id=import_run_id,
            source_name="supabase",
            status="completed",
            watermark_value="snapshot-1",
            imported_count=1,
            skipped_count=0,
            artifact_repaired_count=0,
            started_at="2026-04-04T00:00:00Z",
            completed_at="2026-04-04T00:01:00Z",
            error_code=None,
            error_message=None,
        )


def test_start_local_import_run_persists_active_user_owned_run(tmp_path: Path) -> None:
    db_path = tmp_path / "runtime.db"
    _apply_schema(db_path)
    _activate_user(db_path, user_id="user-1", session_version="1")

    import_run_id = start_local_import_run(
        db_path=db_path,
        busy_timeout_ms=1_000,
        requested_by="user",
        force_reindex=True,
    )
    import_run = get_import_run(
        db_path=db_path,
        busy_timeout_ms=1_000,
        import_run_id=import_run_id,
    )

    assert import_run is not None
    assert import_run.user_id == "user-1"
    assert import_run.status == "running"
