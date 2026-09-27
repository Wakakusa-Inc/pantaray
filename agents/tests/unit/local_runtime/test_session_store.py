from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from pantaray_agents.local_runtime.runtime.control_payload import (
    CLEAR_REASON_EXPIRED,
    CLEAR_REASON_SIGNED_OUT,
    ClearReason,
    normalize_session_version,
)
from pantaray_agents.local_runtime.runtime.session_store import (
    AUTH_CONTEXT_ABSENT_STATE,
    AUTH_CONTEXT_EXPIRED_STATE,
    AUTH_CONTEXT_PRESENT_STATE,
    CloudSessionIdentity,
    apply_cloud_session_clear,
    classify_cloud_session_clear,
    clear_desktop_session,
    import_desktop_session,
    load_active_desktop_session,
    peek_active_desktop_session,
    peek_cloud_session_identity_without_settling,
    peek_expired_cloud_identity,
    peek_pending_cloud_session_expiry,
    read_auth_context_state,
    reset_desktop_session_store,
    settle_cloud_session_expiry,
)
from pantaray_agents.local_runtime.storage.migrations import (
    MigrationError,
)
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


@pytest.fixture(autouse=True)
def reset_session_store_state() -> None:
    reset_desktop_session_store()
    yield
    reset_desktop_session_store()


def test_import_and_load_active_desktop_session(tmp_path: Path) -> None:
    db_path = tmp_path / "runtime.db"
    _apply_schema(db_path)
    expires_at = (datetime.now(UTC) + timedelta(hours=1)).isoformat()

    auth_context_state = import_desktop_session(
        db_path=db_path,
        busy_timeout_ms=1_000,
        user_id="user-1",
        desktop_access_token="header.payload.signature",
        expires_at=expires_at,
        session_version="1",
    )
    session = load_active_desktop_session(
        db_path=db_path,
        busy_timeout_ms=1_000,
        user_id="user-1",
    )

    assert auth_context_state == AUTH_CONTEXT_PRESENT_STATE
    assert session.user_id == "user-1"
    assert session.desktop_access_token == "header.payload.signature"
    assert session.session_version == "1"


def test_import_desktop_session_signs_out_other_active_users(tmp_path: Path) -> None:
    db_path = tmp_path / "runtime.db"
    _apply_schema(db_path)
    expires_at = (datetime.now(UTC) + timedelta(hours=1)).isoformat()

    import_desktop_session(
        db_path=db_path,
        busy_timeout_ms=1_000,
        user_id="user-1",
        desktop_access_token="header.payload.signature",
        expires_at=expires_at,
        session_version="1",
    )
    import_desktop_session(
        db_path=db_path,
        busy_timeout_ms=1_000,
        user_id="user-2",
        desktop_access_token="header.payload.signature",
        expires_at=expires_at,
        session_version="2",
    )

    with pytest.raises(MigrationError, match="desktop session is not active"):
        load_active_desktop_session(
            db_path=db_path,
            busy_timeout_ms=1_000,
            user_id="user-1",
        )
    active = load_active_desktop_session(
        db_path=db_path,
        busy_timeout_ms=1_000,
        user_id="user-2",
    )
    assert active.session_version == "2"


def test_clear_desktop_session_marks_user_signed_out(tmp_path: Path) -> None:
    db_path = tmp_path / "runtime.db"
    _apply_schema(db_path)
    expires_at = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
    import_desktop_session(
        db_path=db_path,
        busy_timeout_ms=1_000,
        user_id="user-1",
        desktop_access_token="header.payload.signature",
        expires_at=expires_at,
        session_version="1",
    )

    result = clear_desktop_session(
        db_path=db_path,
        busy_timeout_ms=1_000,
        user_id="user-1",
    )

    assert result.state == AUTH_CONTEXT_ABSENT_STATE
    assert result.stale is False
    with pytest.raises(MigrationError, match="desktop session is not active"):
        load_active_desktop_session(
            db_path=db_path,
            busy_timeout_ms=1_000,
            user_id="user-1",
        )


def test_import_desktop_session_rejects_older_session_version(tmp_path: Path) -> None:
    db_path = tmp_path / "runtime.db"
    _apply_schema(db_path)
    expires_at = (datetime.now(UTC) + timedelta(hours=1)).isoformat()

    import_desktop_session(
        db_path=db_path,
        busy_timeout_ms=1_000,
        user_id="user-1",
        desktop_access_token="token-new",
        expires_at=expires_at,
        session_version="2",
    )

    with pytest.raises(MigrationError, match="session_version must not go backwards"):
        import_desktop_session(
            db_path=db_path,
            busy_timeout_ms=1_000,
            user_id="user-1",
            desktop_access_token="token-old",
            expires_at=expires_at,
            session_version="1",
        )


def test_token_refresh_keeps_session_active_past_original_expiry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from pantaray_agents.local_runtime.runtime import session_store

    db_path = tmp_path / "runtime.db"
    _apply_schema(db_path)
    now = datetime(2026, 9, 9, tzinfo=UTC)
    monkeypatch.setattr(session_store, "_now_utc", lambda: now)
    import_desktop_session(
        db_path=db_path,
        busy_timeout_ms=1_000,
        user_id="user-1",
        desktop_access_token="token-original",
        expires_at=(now + timedelta(hours=1)).isoformat(),
        session_version="2",
    )
    # Supabase rotates the access token without changing the desktop sign-in version.
    refreshed_expiry = now + timedelta(hours=2)
    import_desktop_session(
        db_path=db_path,
        busy_timeout_ms=1_000,
        user_id="user-1",
        desktop_access_token="token-refreshed",
        expires_at=refreshed_expiry.isoformat(),
        session_version="2",
    )
    now += timedelta(hours=1, minutes=1)
    active_session = load_active_desktop_session(
        db_path=db_path,
        busy_timeout_ms=1_000,
        user_id="user-1",
    )
    assert active_session.desktop_access_token == "token-refreshed"
    assert active_session.expires_at == refreshed_expiry.isoformat().replace(
        "+00:00", "Z"
    )
    assert session_store.read_auth_context_state() == AUTH_CONTEXT_PRESENT_STATE


def test_import_desktop_session_rejects_equal_version_for_different_user(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "runtime.db"
    _apply_schema(db_path)
    expires_at = (datetime.now(UTC) + timedelta(hours=1)).isoformat()

    import_desktop_session(
        db_path=db_path,
        busy_timeout_ms=1_000,
        user_id="user-1",
        desktop_access_token="token-current",
        expires_at=expires_at,
        session_version="2",
    )

    with pytest.raises(
        MigrationError,
        match="session_version conflicts with the active desktop user",
    ):
        import_desktop_session(
            db_path=db_path,
            busy_timeout_ms=1_000,
            user_id="user-2",
            desktop_access_token="token-conflicting",
            expires_at=expires_at,
            session_version="2",
        )

    active_session = load_active_desktop_session(
        db_path=db_path,
        busy_timeout_ms=1_000,
        user_id="user-1",
    )
    assert active_session.desktop_access_token == "token-current"


def _import(db_path: Path, *, user_id: str, version: str, expires_at: str) -> None:
    import_desktop_session(
        db_path=db_path,
        busy_timeout_ms=1_000,
        user_id=user_id,
        desktop_access_token="header.payload.signature",
        expires_at=expires_at,
        session_version=version,
    )


def test_elapsed_session_becomes_expired_and_keeps_its_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from pantaray_agents.local_runtime.runtime import session_store

    db_path = tmp_path / "runtime.db"
    _apply_schema(db_path)
    _import(
        db_path,
        user_id="user-1",
        version="3",
        expires_at=(datetime.now(UTC) + timedelta(seconds=30)).isoformat(),
    )
    generation = peek_active_desktop_session().credential_generation

    monkeypatch.setattr(
        session_store, "_now_utc", lambda: datetime.now(UTC) + timedelta(minutes=5)
    )

    assert read_auth_context_state() == AUTH_CONTEXT_EXPIRED_STATE
    assert peek_active_desktop_session() is None
    identity = peek_expired_cloud_identity()
    assert identity is not None
    assert (
        identity.user_id,
        identity.session_version,
        identity.credential_generation,
    ) == (
        "user-1",
        "3",
        generation,
    )
    with pytest.raises(MigrationError, match="desktop session has expired"):
        load_active_desktop_session(
            db_path=db_path, busy_timeout_ms=1_000, user_id="user-1"
        )


def test_expired_clear_keeps_identity_until_explicit_sign_out(tmp_path: Path) -> None:
    db_path = tmp_path / "runtime.db"
    _apply_schema(db_path)
    expires_at = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
    _import(db_path, user_id="user-1", version="2", expires_at=expires_at)
    generation = peek_active_desktop_session().credential_generation

    expired = clear_desktop_session(
        db_path=db_path,
        busy_timeout_ms=1_000,
        user_id="user-1",
        reason=CLEAR_REASON_EXPIRED,
        expected_session_version="2",
        expected_credential_generation=generation,
    )
    assert (expired.state, expired.stale) == (AUTH_CONTEXT_EXPIRED_STATE, False)
    assert peek_expired_cloud_identity().user_id == "user-1"

    # Re-login with the same version replaces the expired session.
    _import(db_path, user_id="user-1", version="2", expires_at=expires_at)
    assert read_auth_context_state() == AUTH_CONTEXT_PRESENT_STATE
    assert peek_expired_cloud_identity() is None

    clear_desktop_session(
        db_path=db_path,
        busy_timeout_ms=1_000,
        user_id="user-1",
        reason=CLEAR_REASON_EXPIRED,
    )
    signed_out = clear_desktop_session(
        db_path=db_path, busy_timeout_ms=1_000, user_id="user-1"
    )
    assert (signed_out.state, signed_out.stale) == (AUTH_CONTEXT_ABSENT_STATE, False)
    assert peek_expired_cloud_identity() is None


def _signed_in(db_path: Path, *, lifetime_seconds: int = 3_600) -> int:
    """Sign ``user-1`` in at version 4 and return the generation to match."""
    _import(
        db_path,
        user_id="user-1",
        version="4",
        expires_at=(
            datetime.now(UTC) + timedelta(seconds=lifetime_seconds)
        ).isoformat(),
    )
    return peek_active_desktop_session().credential_generation


@pytest.mark.parametrize(
    ("user_id", "session_version", "generation_offset"),
    [
        pytest.param("user-2", "4", 0, id="another-account"),
        pytest.param("user-1", "3", 0, id="another-sign-in"),
        pytest.param("user-1", "4", -1, id="an-older-token"),
    ],
)
def test_a_stale_clear_is_decided_before_it_changes_anything(
    tmp_path: Path,
    user_id: str,
    session_version: str,
    generation_offset: int,
) -> None:
    """A stale callback must leave the running account's session untouched.

    The plan is what a caller checks before stopping any in-flight work, so it
    has to report the staleness itself, and report the session as unchanged.
    """
    db_path = tmp_path / "runtime.db"
    _apply_schema(db_path)
    generation = _signed_in(db_path)
    signed_in = CloudSessionIdentity("present", "user-1", "4")

    plan = classify_cloud_session_clear(
        user_id=user_id,
        reason=CLEAR_REASON_SIGNED_OUT,
        expected_session_version=session_version,
        expected_credential_generation=generation + generation_offset,
    )

    assert plan.stale is True
    assert plan.identity_after == signed_in
    assert peek_cloud_session_identity_without_settling() == signed_in

    result = apply_cloud_session_clear(plan)

    assert (result.state, result.stale) == (AUTH_CONTEXT_PRESENT_STATE, True)
    assert peek_cloud_session_identity_without_settling() == signed_in
    assert (
        load_active_desktop_session(
            db_path=db_path, busy_timeout_ms=1_000, user_id="user-1"
        ).credential_generation
        == generation
    )


@pytest.mark.parametrize(
    ("reason", "identity_after", "state"),
    [
        pytest.param(
            CLEAR_REASON_SIGNED_OUT, None, AUTH_CONTEXT_ABSENT_STATE, id="signed-out"
        ),
        pytest.param(
            CLEAR_REASON_EXPIRED,
            CloudSessionIdentity("expired", "user-1", "4"),
            AUTH_CONTEXT_EXPIRED_STATE,
            id="expired",
        ),
    ],
)
def test_the_planned_identity_is_the_one_the_clear_leaves_behind(
    tmp_path: Path,
    reason: ClearReason,
    identity_after: CloudSessionIdentity | None,
    state: str,
) -> None:
    """The barrier compares the planned identity against the live one."""
    db_path = tmp_path / "runtime.db"
    _apply_schema(db_path)
    generation = _signed_in(db_path)

    plan = classify_cloud_session_clear(
        user_id="user-1",
        reason=reason,
        expected_session_version="4",
        expected_credential_generation=generation,
    )

    assert plan.stale is False
    assert plan.identity_after == identity_after

    result = apply_cloud_session_clear(plan)

    assert (result.state, result.stale) == (state, False)
    assert peek_cloud_session_identity_without_settling() == plan.identity_after


def test_a_sign_out_planned_before_an_expiry_still_reaches_absent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Settling keeps the account, sign-in and generation the plan matched.

    Nothing else runs between classifying and applying a control-socket
    operation, but the store settles an elapsed session on its own. Design 6.2
    lets an explicit sign-out reach ``absent`` from ``expired`` under the same
    version and generation, so the plan still applies.
    """
    from pantaray_agents.local_runtime.runtime import session_store

    db_path = tmp_path / "runtime.db"
    _apply_schema(db_path)
    generation = _signed_in(db_path, lifetime_seconds=30)

    plan = classify_cloud_session_clear(
        user_id="user-1",
        reason=CLEAR_REASON_SIGNED_OUT,
        expected_session_version="4",
        expected_credential_generation=generation,
    )
    assert plan.stale is False

    monkeypatch.setattr(
        session_store, "_now_utc", lambda: datetime.now(UTC) + timedelta(minutes=5)
    )
    assert settle_cloud_session_expiry() == CloudSessionIdentity(
        "expired", "user-1", "4"
    )

    result = apply_cloud_session_clear(plan)

    assert (result.state, result.stale) == (AUTH_CONTEXT_ABSENT_STATE, False)
    assert peek_cloud_session_identity_without_settling() is None


@pytest.mark.parametrize(
    ("user_id", "version"),
    [
        pytest.param("user-1", "4", id="a-refreshed-token"),
        pytest.param("user-2", "5", id="another-account"),
    ],
)
def test_a_plan_overtaken_by_a_new_session_applies_nothing(
    tmp_path: Path, user_id: str, version: str
) -> None:
    """Applying re-checks the plan against the session that is current now.

    The barrier stops in-flight work between classifying and applying, so a
    sign-in that lands in that window must not be signed out by a clear that was
    aimed at the session before it.
    """
    db_path = tmp_path / "runtime.db"
    _apply_schema(db_path)
    generation = _signed_in(db_path)

    plan = classify_cloud_session_clear(
        user_id="user-1",
        reason=CLEAR_REASON_SIGNED_OUT,
        expected_session_version="4",
        expected_credential_generation=generation,
    )
    assert plan.stale is False

    _import(
        db_path,
        user_id=user_id,
        version=version,
        expires_at=(datetime.now(UTC) + timedelta(hours=1)).isoformat(),
    )

    result = apply_cloud_session_clear(plan)

    assert (result.state, result.stale) == (AUTH_CONTEXT_PRESENT_STATE, True)
    assert peek_cloud_session_identity_without_settling() == CloudSessionIdentity(
        "present", user_id, version
    )


def test_a_pending_expiry_is_readable_before_it_is_published(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Stopping in-flight work first means seeing the transition before it lands."""
    from pantaray_agents.local_runtime.runtime import session_store

    db_path = tmp_path / "runtime.db"
    _apply_schema(db_path)
    _signed_in(db_path, lifetime_seconds=30)
    assert peek_pending_cloud_session_expiry() is None

    monkeypatch.setattr(
        session_store, "_now_utc", lambda: datetime.now(UTC) + timedelta(minutes=5)
    )
    expired = CloudSessionIdentity("expired", "user-1", "4")

    assert peek_pending_cloud_session_expiry() == expired
    assert peek_cloud_session_identity_without_settling() == CloudSessionIdentity(
        "present", "user-1", "4"
    )

    assert settle_cloud_session_expiry() == expired
    assert peek_cloud_session_identity_without_settling() == expired
    assert settle_cloud_session_expiry() is None
    assert peek_pending_cloud_session_expiry() is None


@pytest.mark.parametrize("value", ["", "seven", "0"])
def test_a_malformed_session_version_is_refused_at_the_boundary(value: str) -> None:
    """The control socket's version field reaches this before it becomes identity.

    Rejecting it as a ``MigrationError`` is what turns a malformed payload into
    an ``invalid_request`` response instead of a session identified by ``"0"``.
    """
    with pytest.raises(MigrationError, match="session_version must"):
        normalize_session_version(value)
