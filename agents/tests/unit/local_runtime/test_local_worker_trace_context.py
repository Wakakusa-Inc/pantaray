from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest

from pantaray_agents.local_runtime.runtime.identity import (
    register_logged_out_owner,
    reset_logged_out_owner,
)
from pantaray_agents.local_runtime.runtime.local_worker import (
    LocalWorkerSpec,
    run_next_local_job,
)
from pantaray_agents.local_runtime.runtime.session_store import (
    import_desktop_session,
    mark_configured,
)
from pantaray_agents.local_runtime.storage.migrations import (
    load_default_migrations,
)
from pantaray_agents.utils.trace_context import get_trace_context

from .migrated_db import prepare_test_database


@pytest.fixture(autouse=True)
def _logged_out_owner() -> Iterator[None]:
    """Startup registers this before any job runs (design 7.1).

    The route identity a claimed job records is derived from it.
    """
    register_logged_out_owner("local-owner")
    yield
    reset_logged_out_owner()


def test_run_next_local_job_sets_trace_context_for_claimed_job(
    monkeypatch, tmp_path: Path
) -> None:
    payload = {
        "job_id": "job-1",
        "process_id": "process-1",
        "user_id": "user-1",
        "suggestion_id": "suggestion-1",
        "action_id": "action-1",
    }
    claimed_job = {
        "job_id": "job-1",
        "job_type": "structure_facts",
        "user_id": "user-1",
        "process_id": "process-1",
        "claimed_by": "test-worker",
        "payload_json": json.dumps(payload),
    }
    seen: list[tuple[str | None, str | None, str | None, str | None, object]] = []

    def _run(_payload: object) -> None:
        ctx = get_trace_context()
        assert ctx is not None
        seen.append(
            (
                ctx.user_id,
                ctx.local_job_id,
                ctx.suggestion_id,
                ctx.action_id,
                ctx.extra.get("process_id"),
            )
        )

    # A background job type is only claimable with a live cloud session.
    session_db_path = tmp_path / "session.db"
    prepare_test_database(
        db_path=session_db_path,
        busy_timeout_ms=1_000,
        migrations=load_default_migrations(),
    )
    mark_configured()
    import_desktop_session(
        db_path=session_db_path,
        busy_timeout_ms=1_000,
        user_id="user-1",
        desktop_access_token="header.payload.signature",
        expires_at="2099-03-22T01:00:00Z",
        session_version="1",
    )
    monkeypatch.setattr(
        "pantaray_agents.local_runtime.runtime.local_worker.current_owner_id",
        lambda: "user-1",
    )
    monkeypatch.setattr(
        "pantaray_agents.local_runtime.runtime.local_worker.peek_next_pending_job_type",
        lambda **_kwargs: "structure_facts",
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
        lambda **_kwargs: None,
    )
    specs = {
        "structure_facts": LocalWorkerSpec(
            job_type="structure_facts",
            parse_payload=json.loads,
            run=_run,
            process_pending_status="pending",
            process_running_status="running",
            process_success_status="success",
            process_failure_status="error",
            success_job_status="completed",
            failure_job_status="failed",
        )
    }

    executed = run_next_local_job(
        db_path=Path("ignored.db"),
        busy_timeout_ms=1_000,
        claimed_by="worker-1",
        specs=specs,
    )

    assert executed is True
    assert seen == [("user-1", "job-1", "suggestion-1", "action-1", "process-1")]
    assert get_trace_context() is None
