from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path

import pytest

from pantaray_agents.local_runtime.runtime.action_queue import (
    build_local_action_enqueue_request,
)
from pantaray_agents.local_runtime.runtime.activity_queue import (
    enqueue_local_activity_summary_job,
)
from pantaray_agents.local_runtime.runtime.admission import admission_closed
from pantaray_agents.local_runtime.runtime.connection_store import (
    ApiKeyConnection,
    ChatGptConnection,
    ChatGptCredential,
    set_llm_connection,
)
from pantaray_agents.local_runtime.runtime.identity import (
    register_logged_out_owner,
    reset_logged_out_owner,
)
from pantaray_agents.local_runtime.runtime.job_claim import finalize_local_job
from pantaray_agents.local_runtime.runtime.job_enqueue import (
    enqueue_local_job,
    enqueue_local_job_with_connection,
)
from pantaray_agents.local_runtime.runtime.job_envelope import (
    LocalJobEnvelopeIntegrityError,
)
from pantaray_agents.local_runtime.runtime.job_payload_builder import (
    build_action_job_payload,
    build_activity_summary_job_payload,
)
from pantaray_agents.local_runtime.runtime.job_payload_models import (
    parse_activity_summary_job_payload_json,
)
from pantaray_agents.local_runtime.runtime.local_worker import (
    LOCAL_ACTIVITY_SUMMARY_JOB_TYPE,
    LocalJobExecutionError,
    LocalWorkerSpec,
    build_default_local_worker_specs,
    drain_local_action_jobs,
    run_next_local_action_job,
    run_next_local_job,
)
from pantaray_agents.local_runtime.runtime.session_store import (
    clear_desktop_session,
    forget_cloud_session,
    import_desktop_session,
    mark_configured,
    reset_desktop_session_store,
)
from pantaray_agents.local_runtime.runtime.suggestion_queue import (
    build_local_suggestion_enqueue_request,
)
from pantaray_agents.local_runtime.storage.migrations import (
    MigrationError,
    load_default_migrations,
)
from pantaray_agents.local_runtime.storage.users import ensure_user_row
from pantaray_agents.tasks.types import (
    ActionJobPayload,
    ActionJobRuntimePayload,
    SuggestionJobPayload,
)

from .migrated_db import prepare_test_database

CLAIM_OWNER = "test-local-worker"
LOGGED_OUT_OWNER_ID = "local-owner"


def _payload(job_id: str) -> ActionJobPayload:
    action_id = f"action-{job_id}"
    return build_action_job_payload(
        {
            "job_id": job_id,
            "process_id": f"process-{job_id}",
            "action_id": action_id,
            "user_id": "user",
            "continuation_ref": {
                "kind": "user_step",
                "user_step_id": f"user-step-{job_id}",
            },
        }
    )


def _enqueue_action_job(
    *, payload: ActionJobPayload, db_path: Path, busy_timeout_ms: int
) -> str:
    del busy_timeout_ms
    with sqlite3.connect(db_path) as connection:
        with connection:
            action_id = payload["action_id"]
            existing = connection.execute(
                "SELECT 1 FROM agent_actions WHERE action_id = ?",
                (action_id,),
            ).fetchone()
            if existing is None:
                continuation = payload["continuation_ref"]
                assert continuation["kind"] == "user_step"
                user_step_id = continuation["user_step_id"]
                message_id = f"message-{action_id}"
                timestamp = "2026-03-22T00:00:01Z"
                connection.execute(
                    """
                    INSERT INTO agent_actions(
                        action_id, user_id, suggestion_id, initial_user_message_id,
                        execution_target_json, status, final_output, prompt_name,
                        prompt_version, created_at, updated_at
                    ) VALUES (?, ?, NULL, ?, '{"kind":"scratch"}', 'queued', '',
                              'action/executing', '1.0', ?, ?)
                    """,
                    (action_id, payload["user_id"], message_id, timestamp, timestamp),
                )
            result = enqueue_local_job(
                connection=connection,
                request=build_local_action_enqueue_request(
                    payload,
                    scheduled_at="2026-03-22T00:00:01Z",
                    suggestion_id=None,
                ),
            )
            if existing is None:
                connection.execute(
                    """
                    INSERT INTO agent_action_steps(
                        step_id, action_id, user_id, step_number, local_step_number,
                        short_step_id, step_type, step_name, status, goal_handle,
                        retry_count, prompt_tokens, completion_tokens,
                        user_message_id, user_message_json, user_request_text,
                        accepted_sequence, adopted_process_id,
                        started_at, completed_at, created_at
                    ) VALUES (?, ?, ?, 1, 1, 'S-1-USER', 'user_request',
                              'user_request', 'success', 'S', 0, 0, 0, ?, ?,
                              'test action', 1, ?, ?, ?, ?)
                    """,
                    (
                        user_step_id,
                        action_id,
                        payload["user_id"],
                        message_id,
                        json.dumps(
                            {
                                "version": 1,
                                "message_id": message_id,
                                "content": "test action",
                                "images": [],
                            }
                        ),
                        payload["process_id"],
                        timestamp,
                        timestamp,
                        timestamp,
                    ),
                )
    return result["job_id"]


@pytest.fixture(autouse=True)
def _reset_owner_state() -> None:
    reset_desktop_session_store()
    register_logged_out_owner(LOGGED_OUT_OWNER_ID)
    # Electron main applies `configure` before the worker can claim anything.
    mark_configured()
    yield
    reset_desktop_session_store()
    reset_logged_out_owner()


def _insert_user(db_path: Path, *, user_id: str = "user") -> None:
    import_desktop_session(
        db_path=db_path,
        busy_timeout_ms=1_000,
        user_id=user_id,
        desktop_access_token="header.payload.signature",
        expires_at="2099-03-22T01:00:00Z",
        session_version="1",
    )


@pytest.fixture
def signed_in(tmp_path: Path) -> None:
    """A live cloud session, the only state a background job is claimable in."""
    session_db_path = tmp_path / "session.db"
    prepare_test_database(
        db_path=session_db_path,
        busy_timeout_ms=1_000,
        migrations=load_default_migrations(),
    )
    _insert_user(session_db_path)


def _make_logged_out_owner(db_path: Path, *, user_id: str = "user") -> None:
    """Own the store the way startup does with no Pantaray account signed in."""
    with sqlite3.connect(db_path) as connection:
        with connection:
            ensure_user_row(
                connection, user_id=user_id, timestamp="2026-03-22T00:00:00Z"
            )
    register_logged_out_owner(user_id)


def _specs_recording_starts(started: list[str]) -> Mapping[str, LocalWorkerSpec]:
    """Default specs whose runners only record which job reached them."""
    default_specs = build_default_local_worker_specs(
        action_runner=lambda payload: started.append(str(payload["job_id"]))
    )
    return {
        **default_specs,
        LOCAL_ACTIVITY_SUMMARY_JOB_TYPE: replace(
            default_specs[LOCAL_ACTIVITY_SUMMARY_JOB_TYPE],
            run=lambda payload: started.append(str(payload["job_id"])),
        ),
    }


def _suggestion_payload(job_id: str) -> SuggestionJobPayload:
    return {
        "job_id": job_id,
        "process_id": f"process-{job_id}",
        "suggestion_id": f"suggestion-{job_id}",
        "user_id": "user",
        "insight_id": f"insight-{job_id}",
        "enqueued_at": "2026-03-22T00:00:01Z",
    }


def _activity_summary_payload(job_id: str) -> dict[str, object]:
    return build_activity_summary_job_payload(
        {
            "job_id": job_id,
            "process_id": f"process-{job_id}",
            "summary_id": f"summary-{job_id}",
            "user_id": "user",
            "enqueued_at": "2026-03-22T00:00:01Z",
            "summary_type": "24h",
            "period_start": "2026-03-21T00:00:00Z",
            "period_end": "2026-03-22T00:00:00Z",
        }
    )


def test_run_next_local_action_job_completes_job(tmp_path: Path) -> None:
    db_path = tmp_path / "runtime.db"
    prepare_test_database(
        db_path=db_path,
        busy_timeout_ms=1_000,
        migrations=load_default_migrations(),
    )
    _insert_user(db_path)
    _enqueue_action_job(
        payload=_payload("job-1"),
        db_path=db_path,
        busy_timeout_ms=1_000,
    )

    called = {"count": 0}

    def _runner(payload: ActionJobRuntimePayload) -> None:
        assert payload["job_id"] == "job-1"
        called["count"] += 1
        finalize_local_job(
            db_path=str(db_path),
            busy_timeout_ms=1_000,
            job_id=payload["job_id"],
            final_status="completed",
            process_final_status="completed",
        )

    executed = run_next_local_action_job(
        db_path=db_path,
        busy_timeout_ms=1_000,
        runner=_runner,
        claimed_by=CLAIM_OWNER,
    )

    assert executed is True
    assert called["count"] == 1
    with sqlite3.connect(db_path) as connection:
        row = connection.execute(
            "SELECT status FROM jobs WHERE job_id = ?", ("job-1",)
        ).fetchone()
        process_row = connection.execute(
            """
            SELECT status, current_job_id
            FROM processes
            WHERE process_id = ?
            """,
            ("process-job-1",),
        ).fetchone()
    assert row is not None
    assert row[0] == "completed"
    assert process_row == ("completed", None)


@pytest.mark.parametrize(
    ("field", "mismatched_value"),
    [
        ("job_id", "job-other"),
        ("process_id", "process-other"),
        ("user_id", "user-other"),
    ],
)
def test_run_next_local_job_rejects_payload_identity_mismatch_before_dispatch(
    tmp_path: Path,
    field: str,
    mismatched_value: str,
) -> None:
    db_path = tmp_path / "runtime.db"
    prepare_test_database(
        db_path=db_path,
        busy_timeout_ms=1_000,
        migrations=load_default_migrations(),
    )
    _insert_user(db_path)
    payload = _payload("job-identity")
    _enqueue_action_job(
        payload=payload,
        db_path=db_path,
        busy_timeout_ms=1_000,
    )
    tampered_payload: dict[str, object] = dict(payload)
    tampered_payload[field] = mismatched_value
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            "UPDATE job_payloads SET payload_json = ? WHERE job_id = ?",
            (json.dumps(tampered_payload), payload["job_id"]),
        )

    dispatched_payloads: list[ActionJobRuntimePayload] = []
    with pytest.raises(LocalJobExecutionError, match="LocalJobPayloadIdentityError"):
        run_next_local_action_job(
            db_path=db_path,
            busy_timeout_ms=1_000,
            runner=dispatched_payloads.append,
            claimed_by=CLAIM_OWNER,
        )

    assert dispatched_payloads == []
    with sqlite3.connect(db_path) as connection:
        job_row = connection.execute(
            "SELECT status, error_code FROM jobs WHERE job_id = ?",
            (payload["job_id"],),
        ).fetchone()
        process_row = connection.execute(
            "SELECT status, current_job_id FROM processes WHERE process_id = ?",
            (payload["process_id"],),
        ).fetchone()
        attempt_row = connection.execute(
            """
            SELECT status, error_code, error_message
            FROM job_attempts
            WHERE job_id = ?
            """,
            (payload["job_id"],),
        ).fetchone()
    assert job_row == ("canceled", "LOCAL_JOB_EXECUTION_FAILED")
    assert process_row == ("canceled", None)
    assert attempt_row is not None
    assert attempt_row[:2] == ("canceled", "LOCAL_JOB_EXECUTION_FAILED")
    assert attempt_row[2].startswith(
        "LocalJobPayloadIdentityError at"
        " pantaray_agents.local_runtime.runtime.job_executor"
        ":_validate_job_payload_identity:"
    )


def test_run_next_local_job_rejects_process_kind_mismatch_before_dispatch(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "runtime.db"
    prepare_test_database(
        db_path=db_path,
        busy_timeout_ms=1_000,
        migrations=load_default_migrations(),
    )
    _insert_user(db_path)
    payload = _payload("job-process-kind")
    _enqueue_action_job(
        payload=payload,
        db_path=db_path,
        busy_timeout_ms=1_000,
    )
    with sqlite3.connect(db_path) as connection:
        connection.execute("DROP TRIGGER trg_action_user_referenced_process_kind")
        connection.execute(
            "UPDATE processes SET kind = 'fact' WHERE process_id = ?",
            (payload["process_id"],),
        )

    dispatched_payloads: list[ActionJobRuntimePayload] = []
    with pytest.raises(LocalJobEnvelopeIntegrityError):
        run_next_local_action_job(
            db_path=db_path,
            busy_timeout_ms=1_000,
            runner=dispatched_payloads.append,
            claimed_by=CLAIM_OWNER,
        )

    assert dispatched_payloads == []
    with sqlite3.connect(db_path) as connection:
        job_row = connection.execute(
            "SELECT status, error_code FROM jobs WHERE job_id = ?",
            (payload["job_id"],),
        ).fetchone()
        process_row = connection.execute(
            "SELECT kind, status, current_job_id FROM processes WHERE process_id = ?",
            (payload["process_id"],),
        ).fetchone()
    assert job_row == ("blocked", "LOCAL_JOB_ENVELOPE_INTEGRITY_ERROR")
    assert process_row == ("fact", "enqueued", None)


def test_run_next_local_action_job_marks_failed_on_runner_error(tmp_path: Path) -> None:
    db_path = tmp_path / "runtime.db"
    prepare_test_database(
        db_path=db_path,
        busy_timeout_ms=1_000,
        migrations=load_default_migrations(),
    )
    _insert_user(db_path)
    _enqueue_action_job(
        payload=_payload("job-2"),
        db_path=db_path,
        busy_timeout_ms=1_000,
    )

    def _runner(payload: ActionJobRuntimePayload) -> None:
        finalize_local_job(
            db_path=str(db_path),
            busy_timeout_ms=1_000,
            job_id=payload["job_id"],
            final_status="canceled",
            process_final_status="canceled",
        )
        raise RuntimeError("boom")

    with pytest.raises(LocalJobExecutionError, match="RuntimeError"):
        run_next_local_action_job(
            db_path=db_path,
            busy_timeout_ms=1_000,
            runner=_runner,
            claimed_by=CLAIM_OWNER,
        )

    with sqlite3.connect(db_path) as connection:
        row = connection.execute(
            "SELECT status FROM jobs WHERE job_id = ?", ("job-2",)
        ).fetchone()
        process_row = connection.execute(
            """
            SELECT status, current_job_id
            FROM processes
            WHERE process_id = ?
            """,
            ("process-job-2",),
        ).fetchone()
        attempt_row = connection.execute(
            """
            SELECT status
            FROM job_attempts
            WHERE job_id = ?
            """,
            ("job-2",),
        ).fetchone()
    assert row is not None
    assert row[0] == "canceled"
    assert process_row == ("canceled", None)
    assert attempt_row == ("canceled",)


def test_run_next_local_action_job_runs_the_logged_out_owners_job(
    tmp_path: Path,
) -> None:
    """With no Pantaray account signed in, the local owner's work still runs."""
    db_path = tmp_path / "runtime.db"
    prepare_test_database(
        db_path=db_path,
        busy_timeout_ms=1_000,
        migrations=load_default_migrations(),
    )
    _make_logged_out_owner(db_path)
    _enqueue_action_job(
        payload=_payload("job-logged-out"),
        db_path=db_path,
        busy_timeout_ms=1_000,
    )

    def _runner(payload: ActionJobRuntimePayload) -> None:
        finalize_local_job(
            db_path=str(db_path),
            busy_timeout_ms=1_000,
            job_id=payload["job_id"],
            final_status="completed",
            process_final_status="completed",
        )

    executed = run_next_local_action_job(
        db_path=db_path,
        busy_timeout_ms=1_000,
        runner=_runner,
        claimed_by=CLAIM_OWNER,
    )

    assert executed is True
    with sqlite3.connect(db_path) as connection:
        row = connection.execute(
            "SELECT status FROM jobs WHERE job_id = ?", ("job-logged-out",)
        ).fetchone()
    assert row == ("completed",)


def test_background_jobs_wait_until_a_stored_connection_can_send(
    tmp_path: Path,
) -> None:
    """Failing a background job is final -- that period's summary never comes
    back -- so it waits until the request could really be sent. A signed-out
    owner's stored connection is such a route, but not while its ChatGPT token
    has lapsed: `llm_proxy/client.py` refuses that before it sends, and main
    renews it on its own, so the job waits like it does for an expired
    session."""
    db_path = tmp_path / "runtime.db"
    prepare_test_database(
        db_path=db_path,
        busy_timeout_ms=1_000,
        migrations=load_default_migrations(),
    )
    _make_logged_out_owner(db_path)
    enqueue_local_activity_summary_job(
        payload=_activity_summary_payload("job-background"),
        db_path=db_path,
        busy_timeout_ms=1_000,
    )
    started: list[str] = []
    specs = _specs_recording_starts(started)

    def claimed() -> bool:
        return run_next_local_job(
            db_path=db_path,
            busy_timeout_ms=1_000,
            claimed_by=CLAIM_OWNER,
            specs=specs,
        )

    assert claimed() is False

    # A ChatGPT token main has not managed to renew yet.
    set_llm_connection(
        ChatGptConnection(
            model="gpt-5.6-sol",
            credential=ChatGptCredential(
                access_token="chatgpt-access-token",
                expires_at="2020-01-01T00:00:00Z",
                account_id="acct-9",
            ),
        )
    )

    assert claimed() is False
    assert started == []
    with sqlite3.connect(db_path) as connection:
        held = connection.execute(
            "SELECT status, claimed_by FROM jobs WHERE job_id = ?",
            ("job-background",),
        ).fetchone()
    assert held == ("queued", None)

    # An API key has no lifetime the runtime can read, so it always sends.
    set_llm_connection(
        ApiKeyConnection(provider="openai", model="gpt-5", api_key="sk-test")
    )

    assert claimed() is True
    assert started == ["job-background"]


def test_run_next_local_action_job_holds_jobs_until_configure_is_applied(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "runtime.db"
    prepare_test_database(
        db_path=db_path,
        busy_timeout_ms=1_000,
        migrations=load_default_migrations(),
    )
    _make_logged_out_owner(db_path)
    _enqueue_action_job(
        payload=_payload("job-unconfigured"),
        db_path=db_path,
        busy_timeout_ms=1_000,
    )
    # Drops the `configure` Electron main has not sent yet.
    reset_desktop_session_store()

    executed = run_next_local_action_job(
        db_path=db_path,
        busy_timeout_ms=1_000,
        runner=lambda _payload: None,
        claimed_by=CLAIM_OWNER,
    )

    assert executed is False
    with sqlite3.connect(db_path) as connection:
        row = connection.execute(
            "SELECT status, claimed_by FROM jobs WHERE job_id = ?",
            ("job-unconfigured",),
        ).fetchone()
    assert row == ("queued", None)


def _queue_one_action_for_the_logged_out_owner(tmp_path: Path) -> Path:
    db_path = tmp_path / "runtime.db"
    prepare_test_database(
        db_path=db_path,
        busy_timeout_ms=1_000,
        migrations=load_default_migrations(),
    )
    _make_logged_out_owner(db_path)
    _enqueue_action_job(
        payload=_payload("job-barrier"),
        db_path=db_path,
        busy_timeout_ms=1_000,
    )
    return db_path


def _claim_barrier_job(db_path: Path, started: list[str]) -> bool:
    return run_next_local_action_job(
        db_path=db_path,
        busy_timeout_ms=1_000,
        runner=lambda payload: started.append(str(payload["job_id"])),
        claimed_by=CLAIM_OWNER,
    )


def test_nothing_is_claimed_while_an_identity_change_is_in_flight(
    tmp_path: Path,
) -> None:
    """The barrier closes admission before it stops the old identity's work, so
    even the Action the user just submitted waits rather than starting against an
    identity that is about to be replaced. It is claimed on the next poll."""
    db_path = _queue_one_action_for_the_logged_out_owner(tmp_path)
    started: list[str] = []

    with admission_closed():
        assert _claim_barrier_job(db_path, started) is False

    assert started == []
    with sqlite3.connect(db_path) as connection:
        held = connection.execute(
            "SELECT status, claimed_by FROM jobs WHERE job_id = ?",
            ("job-barrier",),
        ).fetchone()
    assert held == ("queued", None)

    assert _claim_barrier_job(db_path, started) is True
    assert started == ["job-barrier"]


def test_a_barrier_that_fails_part_way_still_reopens_admission(
    tmp_path: Path,
) -> None:
    """Otherwise one failed identity change would leave the runtime claiming
    nothing at all for the rest of the process."""
    db_path = _queue_one_action_for_the_logged_out_owner(tmp_path)
    started: list[str] = []

    with pytest.raises(RuntimeError):
        with admission_closed():
            raise RuntimeError("the identity swap failed")

    assert _claim_barrier_job(db_path, started) is True
    assert started == ["job-barrier"]


def test_an_expired_session_runs_the_users_job_and_holds_the_background_one(
    tmp_path: Path,
) -> None:
    """Nothing blocks the GUI from submitting while a session is expired, so the
    turn must reach its visible failure instead of sitting queued in silence.
    The saved connection does not release the background job either: an expired
    session refuses every request rather than falling back to it."""
    db_path = tmp_path / "runtime.db"
    prepare_test_database(
        db_path=db_path,
        busy_timeout_ms=1_000,
        migrations=load_default_migrations(),
    )
    _insert_user(db_path)
    set_llm_connection(
        ApiKeyConnection(provider="openai", model="gpt-5", api_key="sk-test")
    )
    enqueue_local_activity_summary_job(
        payload=_activity_summary_payload("job-background"),
        db_path=db_path,
        busy_timeout_ms=1_000,
    )
    _enqueue_action_job(
        payload=_payload("job-expired"),
        db_path=db_path,
        busy_timeout_ms=1_000,
    )
    expired = clear_desktop_session(
        db_path=db_path,
        busy_timeout_ms=1_000,
        user_id="user",
        reason="expired",
    )
    assert expired.state == "expired"
    started: list[str] = []

    assert (
        run_next_local_job(
            db_path=db_path,
            busy_timeout_ms=1_000,
            claimed_by=CLAIM_OWNER,
            specs=_specs_recording_starts(started),
        )
        is True
    )

    assert started == ["job-expired"]
    with sqlite3.connect(db_path) as connection:
        held = connection.execute(
            "SELECT status, claimed_by FROM jobs WHERE job_id = ?",
            ("job-background",),
        ).fetchone()
    assert held == ("queued", None)


def test_run_next_local_action_job_ignores_the_logged_out_owners_job_after_sign_in(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "runtime.db"
    prepare_test_database(
        db_path=db_path,
        busy_timeout_ms=1_000,
        migrations=load_default_migrations(),
    )
    _make_logged_out_owner(db_path)
    _enqueue_action_job(
        payload=_payload("job-before-sign-in"),
        db_path=db_path,
        busy_timeout_ms=1_000,
    )
    _insert_user(db_path, user_id="account-user")

    executed = run_next_local_action_job(
        db_path=db_path,
        busy_timeout_ms=1_000,
        runner=lambda _payload: None,
        claimed_by=CLAIM_OWNER,
    )

    assert executed is False
    with sqlite3.connect(db_path) as connection:
        row = connection.execute(
            "SELECT status, claimed_by FROM jobs WHERE job_id = ?",
            ("job-before-sign-in",),
        ).fetchone()
    assert row == ("queued", None)


def test_run_next_local_action_job_ignores_an_accounts_job_after_sign_out(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "runtime.db"
    prepare_test_database(
        db_path=db_path,
        busy_timeout_ms=1_000,
        migrations=load_default_migrations(),
    )
    _insert_user(db_path)
    _enqueue_action_job(
        payload=_payload("job-no-session"),
        db_path=db_path,
        busy_timeout_ms=1_000,
    )
    forget_cloud_session()

    executed = run_next_local_action_job(
        db_path=db_path,
        busy_timeout_ms=1_000,
        runner=lambda _payload: None,
        claimed_by=CLAIM_OWNER,
    )

    assert executed is False
    with sqlite3.connect(db_path) as connection:
        row = connection.execute(
            "SELECT status, claimed_by FROM jobs WHERE job_id = ?",
            ("job-no-session",),
        ).fetchone()
    assert row == ("queued", None)


def test_run_next_local_action_job_ignores_another_users_job(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "runtime.db"
    prepare_test_database(
        db_path=db_path,
        busy_timeout_ms=1_000,
        migrations=load_default_migrations(),
    )
    _insert_user(db_path)
    _enqueue_action_job(
        payload=_payload("job-owner-mismatch"),
        db_path=db_path,
        busy_timeout_ms=1_000,
    )
    import_desktop_session(
        db_path=db_path,
        busy_timeout_ms=1_000,
        user_id="other-user",
        desktop_access_token="header.payload.signature",
        expires_at="2099-03-22T01:00:00Z",
        session_version="2",
    )

    executed = run_next_local_action_job(
        db_path=db_path,
        busy_timeout_ms=1_000,
        runner=lambda _payload: None,
        claimed_by=CLAIM_OWNER,
    )

    assert executed is False
    with sqlite3.connect(db_path) as connection:
        row = connection.execute(
            "SELECT status, claimed_by FROM jobs WHERE job_id = ?",
            ("job-owner-mismatch",),
        ).fetchone()
        process_row = connection.execute(
            "SELECT status, current_job_id FROM processes WHERE process_id = ?",
            ("process-job-owner-mismatch",),
        ).fetchone()
        attempt_count = connection.execute(
            "SELECT COUNT(*) FROM job_attempts WHERE job_id = ?",
            ("job-owner-mismatch",),
        ).fetchone()
    assert row == ("queued", None)
    assert process_row == ("enqueued", None)
    assert attempt_count == (0,)


def test_run_next_local_action_job_requeues_if_session_changes_after_claim(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from pantaray_agents.local_runtime.runtime import job_executor
    from pantaray_agents.local_runtime.runtime.identity import (
        verify_current_owner,
    )

    db_path = tmp_path / "runtime.db"
    prepare_test_database(
        db_path=db_path,
        busy_timeout_ms=1_000,
        migrations=load_default_migrations(),
    )
    _insert_user(db_path)
    _enqueue_action_job(
        payload=_payload("job-session-race"),
        db_path=db_path,
        busy_timeout_ms=1_000,
    )
    requeue_attempts = 0
    sleep_delays: list[float] = []
    requeue = job_executor.requeue_claimed_local_job_after_dispatch_failure

    def _requeue_after_transient_failure(**kwargs: object) -> None:
        nonlocal requeue_attempts
        requeue_attempts += 1
        if requeue_attempts == 1:
            raise sqlite3.OperationalError("database is locked")
        requeue(**kwargs)

    def _switch_session_before_dispatch(owner_user_id: str) -> None:
        import_desktop_session(
            db_path=db_path,
            busy_timeout_ms=1_000,
            user_id="other-user",
            desktop_access_token="header.payload.signature",
            expires_at="2099-03-22T01:00:00Z",
            session_version="2",
        )
        verify_current_owner(owner_user_id)

    monkeypatch.setattr(
        job_executor,
        "verify_current_owner",
        _switch_session_before_dispatch,
    )
    monkeypatch.setattr(
        job_executor,
        "requeue_claimed_local_job_after_dispatch_failure",
        _requeue_after_transient_failure,
    )
    monkeypatch.setattr(
        job_executor.time,
        "sleep",
        sleep_delays.append,
    )

    executed = run_next_local_action_job(
        db_path=db_path,
        busy_timeout_ms=1_000,
        runner=lambda _payload: None,
        claimed_by=CLAIM_OWNER,
    )

    assert executed is False
    with sqlite3.connect(db_path) as connection:
        job_row = connection.execute(
            "SELECT status, claimed_by FROM jobs WHERE job_id = ?",
            ("job-session-race",),
        ).fetchone()
        process_row = connection.execute(
            "SELECT status, current_job_id FROM processes WHERE process_id = ?",
            ("process-job-session-race",),
        ).fetchone()
        attempt_row = connection.execute(
            "SELECT status, error_code FROM job_attempts WHERE job_id = ?",
            ("job-session-race",),
        ).fetchone()
    assert job_row == ("queued", None)
    assert process_row == ("enqueued", None)
    assert attempt_row == ("failed", "LOCAL_JOB_DISPATCH_FAILED")
    assert requeue_attempts == 2
    assert sleep_delays == [0.1]


def test_action_enqueue_request_returns_existing_active_job_for_same_action(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "runtime.db"
    prepare_test_database(
        db_path=db_path,
        busy_timeout_ms=1_000,
        migrations=load_default_migrations(),
    )
    _insert_user(db_path)

    first_job_id = _enqueue_action_job(
        payload={
            **_payload("job-duplicate-1"),
            "action_id": "same-action",
        },
        db_path=db_path,
        busy_timeout_ms=1_000,
    )
    second_job_id = _enqueue_action_job(
        payload={
            **_payload("job-duplicate-2"),
            "action_id": "same-action",
        },
        db_path=db_path,
        busy_timeout_ms=1_000,
    )

    assert first_job_id == "job-duplicate-1"
    assert second_job_id == "job-duplicate-1"
    with sqlite3.connect(db_path) as connection:
        row = connection.execute("SELECT COUNT(*) FROM jobs").fetchone()
        event_row = connection.execute(
            "SELECT COUNT(*) FROM process_events WHERE event_name = 'action_requested'"
        ).fetchone()
    assert row == (1,)
    assert event_row == (0,)


def test_run_next_local_action_job_returns_false_when_queue_empty(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "runtime.db"
    prepare_test_database(
        db_path=db_path,
        busy_timeout_ms=1_000,
        migrations=load_default_migrations(),
    )

    executed = run_next_local_action_job(
        db_path=db_path,
        busy_timeout_ms=1_000,
        runner=lambda _: None,
        claimed_by=CLAIM_OWNER,
    )

    assert executed is False


def test_drain_local_action_jobs_executes_up_to_max_jobs(tmp_path: Path) -> None:
    db_path = tmp_path / "runtime.db"
    prepare_test_database(
        db_path=db_path,
        busy_timeout_ms=1_000,
        migrations=load_default_migrations(),
    )
    _insert_user(db_path)
    for index in range(3):
        _enqueue_action_job(
            payload=_payload(f"job-{index}"),
            db_path=db_path,
            busy_timeout_ms=1_000,
        )

    call_count = {"value": 0}

    def _runner(_: ActionJobRuntimePayload) -> None:
        call_count["value"] += 1

    drained = drain_local_action_jobs(
        db_path=db_path,
        busy_timeout_ms=1_000,
        runner=_runner,
        max_jobs=2,
        claimed_by=CLAIM_OWNER,
    )

    assert drained == 2
    assert call_count["value"] == 2


def test_enqueue_local_activity_summary_job_returns_existing_summary_id_when_deduped(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "runtime.db"
    prepare_test_database(
        db_path=db_path,
        busy_timeout_ms=1_000,
        migrations=load_default_migrations(),
    )
    _insert_user(db_path)

    first = enqueue_local_activity_summary_job(
        payload=_activity_summary_payload("job-activity-summary-1"),
        db_path=db_path,
        busy_timeout_ms=1_000,
    )
    second = enqueue_local_activity_summary_job(
        payload={
            **_activity_summary_payload("job-activity-summary-2"),
            "summary_id": "summary-job-activity-summary-1",
        },
        db_path=db_path,
        busy_timeout_ms=1_000,
    )

    assert first["inserted_new"] is True
    assert second["inserted_new"] is False
    assert second["job_id"] == first["job_id"]
    assert second["process_id"] == first["process_id"]


def test_drain_local_action_jobs_rejects_invalid_max_jobs(tmp_path: Path) -> None:
    db_path = tmp_path / "runtime.db"
    prepare_test_database(
        db_path=db_path,
        busy_timeout_ms=1_000,
        migrations=load_default_migrations(),
    )

    with pytest.raises(MigrationError, match="max_jobs"):
        drain_local_action_jobs(
            db_path=db_path,
            busy_timeout_ms=1_000,
            runner=lambda _: None,
            max_jobs=0,
            claimed_by=CLAIM_OWNER,
        )


def test_run_next_local_job_completes_suggestion_job(tmp_path: Path) -> None:
    db_path = tmp_path / "runtime.db"
    prepare_test_database(
        db_path=db_path,
        busy_timeout_ms=1_000,
        migrations=load_default_migrations(),
    )
    _insert_user(db_path)
    enqueue_local_job_with_connection(
        db_path=str(db_path),
        busy_timeout_ms=1_000,
        request=build_local_suggestion_enqueue_request(
            _suggestion_payload("suggestion-job-1")
        ),
    )

    called = {"count": 0}

    def _action_runner(_: ActionJobRuntimePayload) -> None:
        called["count"] += 100

    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(
            "pantaray_agents.local_runtime.runtime.local_worker.run_suggestion_job",
            lambda payload: called.__setitem__(
                "count",
                called["count"] + (1 if payload["job_id"] == "suggestion-job-1" else 0),
            ),
        )
        executed = run_next_local_job(
            db_path=db_path,
            busy_timeout_ms=1_000,
            claimed_by=CLAIM_OWNER,
            specs=build_default_local_worker_specs(action_runner=_action_runner),
        )

    assert executed is True
    assert called["count"] == 1
    with sqlite3.connect(db_path) as connection:
        row = connection.execute(
            "SELECT status FROM jobs WHERE job_id = ?",
            ("suggestion-job-1",),
        ).fetchone()
        process_row = connection.execute(
            """
            SELECT status, current_job_id
            FROM processes
            WHERE process_id = ?
            """,
            ("process-suggestion-job-1",),
        ).fetchone()
    assert row == ("completed",)
    assert process_row == ("success", None)


def test_run_next_local_job_records_why_a_background_job_failed(
    tmp_path: Path,
) -> None:
    """The terminal says why, without copying the exception's private text."""
    db_path = tmp_path / "runtime.db"
    prepare_test_database(
        db_path=db_path,
        busy_timeout_ms=1_000,
        migrations=load_default_migrations(),
    )
    _insert_user(db_path)
    enqueue_local_job_with_connection(
        db_path=str(db_path),
        busy_timeout_ms=1_000,
        request=build_local_suggestion_enqueue_request(
            _suggestion_payload("suggestion-job-failed")
        ),
    )

    def _fail(_payload: SuggestionJobPayload) -> None:
        raise RuntimeError("private-note-body /Users/private/notes.md")

    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(
            "pantaray_agents.local_runtime.runtime.local_worker.run_suggestion_job",
            _fail,
        )
        with pytest.raises(LocalJobExecutionError, match="RuntimeError"):
            run_next_local_job(
                db_path=db_path,
                busy_timeout_ms=1_000,
                claimed_by=CLAIM_OWNER,
                specs=build_default_local_worker_specs(action_runner=lambda _: None),
            )

    with sqlite3.connect(db_path) as connection:
        job_row = connection.execute(
            "SELECT status, error_code FROM jobs WHERE job_id = ?",
            ("suggestion-job-failed",),
        ).fetchone()
        attempt_row = connection.execute(
            """
            SELECT status, error_code, error_message
            FROM job_attempts
            WHERE job_id = ?
            """,
            ("suggestion-job-failed",),
        ).fetchone()

    assert job_row == ("failed", "LOCAL_JOB_EXECUTION_FAILED")
    assert attempt_row is not None
    assert attempt_row[:2] == ("failed", "LOCAL_JOB_EXECUTION_FAILED")
    # The class alone is ambiguous across raise sites, so the reason names the
    # innermost frame rather than the executor that caught it.
    assert attempt_row[2].startswith(f"RuntimeError at {__name__}:_fail:")
    assert "private-note-body" not in attempt_row[2]
    assert "/Users/private/notes.md" not in attempt_row[2]


def test_build_default_local_worker_specs_includes_phase4_job_types() -> None:
    specs = build_default_local_worker_specs(action_runner=lambda _: None)

    assert "generate_insight" in specs
    assert "memory_update" in specs
    assert specs["execute_action_subagent"].finalize_after_run is False


def test_run_next_local_job_raises_when_terminal_finalize_fails(
    monkeypatch: pytest.MonkeyPatch,
    signed_in: None,
) -> None:
    claimed_job = {
        "job_id": "job-finalize-fail",
        "job_type": LOCAL_ACTIVITY_SUMMARY_JOB_TYPE,
        "user_id": "user",
        "process_id": "process-job-finalize-fail",
        "claimed_by": CLAIM_OWNER,
        "payload_json": json.dumps(_activity_summary_payload("job-finalize-fail")),
    }

    def _finalize_failure(**_kwargs: object) -> None:
        raise RuntimeError("finalize boom")

    monkeypatch.setattr(
        "pantaray_agents.local_runtime.runtime.local_worker.current_owner_id",
        lambda: "user",
    )
    monkeypatch.setattr(
        "pantaray_agents.local_runtime.runtime.local_worker.peek_next_pending_job_type",
        lambda **_kwargs: LOCAL_ACTIVITY_SUMMARY_JOB_TYPE,
    )
    monkeypatch.setattr(
        "pantaray_agents.local_runtime.runtime.local_worker.claim_next_pending_job",
        lambda **_kwargs: claimed_job,
    )
    monkeypatch.setattr(
        "pantaray_agents.local_runtime.runtime.job_executor.verify_current_owner",
        lambda _user_id: None,
    )
    monkeypatch.setattr(
        "pantaray_agents.local_runtime.runtime.job_executor.finalize_local_job",
        _finalize_failure,
    )
    specs = {
        LOCAL_ACTIVITY_SUMMARY_JOB_TYPE: LocalWorkerSpec(
            job_type=LOCAL_ACTIVITY_SUMMARY_JOB_TYPE,
            parse_payload=parse_activity_summary_job_payload_json,
            run=lambda _payload: None,
            process_pending_status="pending",
            process_running_status="running",
            process_success_status="completed",
            process_failure_status="error",
            success_job_status="completed",
            failure_job_status="failed",
        )
    }

    with pytest.raises(RuntimeError, match="finalize boom"):
        run_next_local_job(
            db_path=Path("ignored.db"),
            busy_timeout_ms=1_000,
            claimed_by=CLAIM_OWNER,
            specs=specs,
        )


def test_run_next_local_job_retries_only_terminal_write_after_transient_failure(
    monkeypatch: pytest.MonkeyPatch,
    signed_in: None,
) -> None:
    claimed_job = {
        "job_id": "job-finalize-retry",
        "job_type": LOCAL_ACTIVITY_SUMMARY_JOB_TYPE,
        "user_id": "user",
        "process_id": "process-job-finalize-retry",
        "claimed_by": CLAIM_OWNER,
        "payload_json": json.dumps(_activity_summary_payload("job-finalize-retry")),
    }
    run_count = 0
    finalize_count = 0
    sleep_delays: list[float] = []

    def _run(_payload: object) -> None:
        nonlocal run_count
        run_count += 1

    def _finalize(**_kwargs: object) -> None:
        nonlocal finalize_count
        finalize_count += 1
        if finalize_count == 1:
            raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(
        "pantaray_agents.local_runtime.runtime.local_worker.current_owner_id",
        lambda: "user",
    )
    monkeypatch.setattr(
        "pantaray_agents.local_runtime.runtime.local_worker.peek_next_pending_job_type",
        lambda **_kwargs: LOCAL_ACTIVITY_SUMMARY_JOB_TYPE,
    )
    monkeypatch.setattr(
        "pantaray_agents.local_runtime.runtime.local_worker.claim_next_pending_job",
        lambda **_kwargs: claimed_job,
    )
    monkeypatch.setattr(
        "pantaray_agents.local_runtime.runtime.job_executor.verify_current_owner",
        lambda _user_id: None,
    )
    monkeypatch.setattr(
        "pantaray_agents.local_runtime.runtime.job_executor.finalize_local_job",
        _finalize,
    )
    monkeypatch.setattr(
        "pantaray_agents.local_runtime.runtime.job_executor.time.sleep",
        lambda delay: sleep_delays.append(delay),
    )
    specs = {
        LOCAL_ACTIVITY_SUMMARY_JOB_TYPE: LocalWorkerSpec(
            job_type=LOCAL_ACTIVITY_SUMMARY_JOB_TYPE,
            parse_payload=parse_activity_summary_job_payload_json,
            run=_run,
            process_pending_status="pending",
            process_running_status="running",
            process_success_status="completed",
            process_failure_status="error",
            success_job_status="completed",
            failure_job_status="failed",
        )
    }

    assert (
        run_next_local_job(
            db_path=Path("ignored.db"),
            busy_timeout_ms=1_000,
            claimed_by=CLAIM_OWNER,
            specs=specs,
        )
        is True
    )
    assert run_count == 1
    assert finalize_count == 2
    assert sleep_delays == [0.1]


def test_run_next_local_job_logs_activity_failure_details(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    signed_in: None,
) -> None:
    claimed_job = {
        "job_id": "job-run-fail",
        "job_type": LOCAL_ACTIVITY_SUMMARY_JOB_TYPE,
        "user_id": "user",
        "process_id": "process-job-run-fail",
        "claimed_by": CLAIM_OWNER,
        "payload_json": json.dumps(_activity_summary_payload("job-run-fail")),
    }

    finalized: list[dict[str, object]] = []

    monkeypatch.setattr(
        "pantaray_agents.local_runtime.runtime.local_worker.current_owner_id",
        lambda: "user",
    )
    monkeypatch.setattr(
        "pantaray_agents.local_runtime.runtime.local_worker.peek_next_pending_job_type",
        lambda **_kwargs: LOCAL_ACTIVITY_SUMMARY_JOB_TYPE,
    )
    monkeypatch.setattr(
        "pantaray_agents.local_runtime.runtime.local_worker.claim_next_pending_job",
        lambda **_kwargs: claimed_job,
    )
    monkeypatch.setattr(
        "pantaray_agents.local_runtime.runtime.job_executor.verify_current_owner",
        lambda _user_id: None,
    )
    monkeypatch.setattr(
        "pantaray_agents.local_runtime.runtime.job_executor.finalize_local_job",
        lambda **kwargs: finalized.append(kwargs),
    )
    specs = {
        LOCAL_ACTIVITY_SUMMARY_JOB_TYPE: LocalWorkerSpec(
            job_type=LOCAL_ACTIVITY_SUMMARY_JOB_TYPE,
            parse_payload=parse_activity_summary_job_payload_json,
            run=lambda _payload: (_ for _ in ()).throw(RuntimeError("boom")),
            process_pending_status="pending",
            process_running_status="running",
            process_success_status="completed",
            process_failure_status="error",
            success_job_status="completed",
            failure_job_status="failed",
        )
    }

    with pytest.raises(LocalJobExecutionError, match="RuntimeError"):
        run_next_local_job(
            db_path=Path("ignored.db"),
            busy_timeout_ms=1_000,
            claimed_by=CLAIM_OWNER,
            specs=specs,
        )

    failure_records = [
        json.loads(record.getMessage())
        for record in caplog.records
        if "LOCAL_JOB_FAILED" in record.getMessage()
    ]
    assert len(failure_records) == 1
    assert failure_records[0]["error_class"] == "RuntimeError"
    chain = failure_records[0]["exception_chain"]
    assert "omitted" in chain[0]["message"]
    assert any(
        frame["function"] == "execute_claimed_local_job" for frame in chain[0]["stack"]
    )
    assert "error_message" not in failure_records[0]
    assert failure_records[0]["job_id_fp"]
    assert finalized[0]["final_status"] == "failed"
