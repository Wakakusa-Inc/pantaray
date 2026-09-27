from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from pantaray_agents.local_runtime.memory_catalog.erasure import (
    ProtectedOwnerErasureError,
    erase_user_memory_offline,
)
from pantaray_agents.local_runtime.runtime.identity import (
    LocalOwnerUnavailableError,
    OwnerMismatchError,
    current_owner_id,
    register_logged_out_owner,
    reset_logged_out_owner,
    verify_current_owner,
)
from pantaray_agents.local_runtime.runtime.local_owner import (
    LOCAL_OWNER_ROW_ID,
    ensure_logged_out_owner,
)
from pantaray_agents.local_runtime.runtime.session_store import (
    clear_desktop_session,
    import_desktop_session,
    reset_desktop_session_store,
)
from pantaray_agents.local_runtime.storage.migrations.specs import (
    load_default_migrations,
)

from .migrated_db import prepare_test_database


@pytest.fixture(autouse=True)
def _reset_runtime_identity() -> None:
    reset_desktop_session_store()
    reset_logged_out_owner()
    yield
    reset_desktop_session_store()
    reset_logged_out_owner()


def _prepared_store(tmp_path: Path) -> Path:
    db_path = tmp_path / "runtime.db"
    prepare_test_database(
        db_path=db_path, busy_timeout_ms=1_000, migrations=load_default_migrations()
    )
    return db_path


def test_logged_out_owner_is_created_once_per_store(tmp_path: Path) -> None:
    db_path = _prepared_store(tmp_path)

    first = ensure_logged_out_owner(db_path=db_path, busy_timeout_ms=1_000)
    second = ensure_logged_out_owner(db_path=db_path, busy_timeout_ms=1_000)

    assert first == second
    with sqlite3.connect(db_path) as connection:
        owner_rows = connection.execute(
            "SELECT id, user_id FROM local_owner"
        ).fetchall()
        user_rows = connection.execute("SELECT user_id FROM users").fetchall()
    assert owner_rows == [(LOCAL_OWNER_ROW_ID, first)]
    assert user_rows == [(first,)]


def test_current_owner_requires_registration(tmp_path: Path) -> None:
    with pytest.raises(LocalOwnerUnavailableError):
        current_owner_id()


def test_current_owner_follows_the_cloud_session(tmp_path: Path) -> None:
    db_path = _prepared_store(tmp_path)
    owner_id = ensure_logged_out_owner(db_path=db_path, busy_timeout_ms=1_000)
    register_logged_out_owner(owner_id)
    assert current_owner_id() == owner_id

    expires_at = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
    import_desktop_session(
        db_path=db_path,
        busy_timeout_ms=1_000,
        user_id="account-user",
        desktop_access_token="token",
        expires_at=expires_at,
        session_version="1",
    )
    assert current_owner_id() == "account-user"

    expired = clear_desktop_session(
        db_path=db_path,
        busy_timeout_ms=1_000,
        user_id="account-user",
        reason="expired",
    )
    assert expired.state == "expired"
    assert current_owner_id() == "account-user"

    clear_desktop_session(
        db_path=db_path, busy_timeout_ms=1_000, user_id="account-user"
    )
    assert current_owner_id() == owner_id
    with sqlite3.connect(db_path) as connection:
        owner_row = connection.execute("SELECT user_id FROM local_owner").fetchone()
    assert owner_row == (owner_id,)


def _sign_in(db_path: Path, *, user_id: str, session_version: str) -> None:
    import_desktop_session(
        db_path=db_path,
        busy_timeout_ms=1_000,
        user_id=user_id,
        desktop_access_token="token",
        expires_at=(datetime.now(UTC) + timedelta(hours=1)).isoformat(),
        session_version=session_version,
    )


def test_verify_current_owner_rejects_work_owned_by_anyone_else(
    tmp_path: Path,
) -> None:
    """Owner-scoped work never crosses owners, whoever is current (design 6.10)."""
    db_path = _prepared_store(tmp_path)
    owner_id = ensure_logged_out_owner(db_path=db_path, busy_timeout_ms=1_000)
    register_logged_out_owner(owner_id)

    verify_current_owner(owner_id)
    with pytest.raises(OwnerMismatchError):
        verify_current_owner("account-a")

    _sign_in(db_path, user_id="account-a", session_version="1")
    verify_current_owner("account-a")
    for other in (owner_id, "account-b"):
        with pytest.raises(OwnerMismatchError):
            verify_current_owner(other)

    clear_desktop_session(
        db_path=db_path, busy_timeout_ms=1_000, user_id="account-a", reason="expired"
    )
    # An expired session still owns its data; only cloud calls fail.
    verify_current_owner("account-a")

    _sign_in(db_path, user_id="account-b", session_version="2")
    verify_current_owner("account-b")
    with pytest.raises(OwnerMismatchError):
        verify_current_owner("account-a")

    clear_desktop_session(db_path=db_path, busy_timeout_ms=1_000, user_id="account-b")
    verify_current_owner(owner_id)
    with pytest.raises(OwnerMismatchError):
        verify_current_owner("account-b")


def test_user_erasure_rejects_the_logged_out_owner(tmp_path: Path) -> None:
    db_path = _prepared_store(tmp_path)
    owner_id = ensure_logged_out_owner(db_path=db_path, busy_timeout_ms=1_000)

    with pytest.raises(ProtectedOwnerErasureError):
        erase_user_memory_offline(
            db_path=db_path,
            busy_timeout_ms=1_000,
            artifact_root=tmp_path / "artifacts",
            user_id=owner_id,
        )

    with sqlite3.connect(db_path) as connection:
        pending = connection.execute(
            "SELECT COUNT(*) FROM memory_artifact_deletions WHERE user_id = ?",
            (owner_id,),
        ).fetchone()
        users = connection.execute("SELECT user_id FROM users").fetchall()
    assert pending == (0,)
    assert users == [(owner_id,)]
