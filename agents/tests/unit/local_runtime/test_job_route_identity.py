"""The route identity a claimed job records, and what a change to it does.

Every identity here is changed through the real stores, so a test fails when the
identity stops covering the sign-in, the account or the credential it claims to.
"""

from __future__ import annotations

import asyncio
import sqlite3
from collections.abc import Callable, Iterator, Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

import pytest
from tests.unit.local_runtime.test_direct_llm_dispatch import SendBoundary, responder
from tests.unit.local_runtime.test_llm_proxy_client import _FakeHttpResponse
from tests.unit.local_runtime.test_llm_route_decision import (
    CLOUD_RESPONSE_PAYLOAD,
    CloudBoundary,
    file_contents,
    refuse_file_reads,
)
from tests.unit.local_runtime.test_web_tools_client import (
    _patch_proxy_transport,
    _patch_tavily,
    _RecordingTavilyClient,
)

from pantaray_agents.local_runtime.llm_proxy import direct
from pantaray_agents.local_runtime.llm_proxy.client import LocalLlmProxyClient
from pantaray_agents.local_runtime.runtime import worker_daemon
from pantaray_agents.local_runtime.runtime.action_queue import (
    build_local_action_enqueue_request,
)
from pantaray_agents.local_runtime.runtime.connection_store import (
    ApiKeyConnection,
    set_llm_connection,
)
from pantaray_agents.local_runtime.runtime.identity import (
    register_logged_out_owner,
    reset_logged_out_owner,
)
from pantaray_agents.local_runtime.runtime.job_capacity import LocalWorkerCapacity
from pantaray_agents.local_runtime.runtime.job_claim import claim_next_pending_job
from pantaray_agents.local_runtime.runtime.job_enqueue import (
    enqueue_local_job,
    enqueue_local_job_with_connection,
)
from pantaray_agents.local_runtime.runtime.job_payload_builder import (
    build_action_job_payload,
)
from pantaray_agents.local_runtime.runtime.job_route_identity import (
    require_current_route_identity,
)
from pantaray_agents.local_runtime.runtime.job_types import (
    LOCAL_ACTION_JOB_TYPE,
    LOCAL_SUGGESTION_JOB_TYPE,
)
from pantaray_agents.local_runtime.runtime.local_worker import (
    LocalJobExecutionError,
    LocalWorkerSpec,
    build_default_local_worker_specs,
    run_next_local_job,
)
from pantaray_agents.local_runtime.runtime.session_store import (
    import_desktop_session,
    mark_configured,
)
from pantaray_agents.local_runtime.runtime.suggestion_queue import (
    build_local_suggestion_enqueue_request,
)
from pantaray_agents.local_runtime.storage.migrations import (
    load_default_migrations,
)
from pantaray_agents.local_runtime.web_tools.client import (
    WebToolsWrapperContext,
    invoke_web_tools_wrapper,
)
from pantaray_agents.tasks.types import ActionJobPayload, SuggestionJobPayload
from pantaray_agents.utils.llm_types import types
from pantaray_llm.profiles import ACTIVITY_SUMMARY_PROFILE_ID, WEB_SEARCH_PROFILE_ID

from .action_seed import insert_agent_action
from .migrated_db import prepare_test_database

BUSY_TIMEOUT_MS = 1_000
CLAIM_OWNER = "test-job-route-identity"
LOGGED_OUT_OWNER_ID = "local-owner"
USER_ID = "user"
LLM_PROXY_URL = "https://llm.example.test/v1/llm/proxy"


@pytest.fixture(autouse=True)
def _configured_runtime() -> Iterator[None]:
    """Startup registers the owner; Electron main then applies `configure`.

    The session and connection stores are reset around every test by the root
    conftest.
    """
    register_logged_out_owner(LOGGED_OUT_OWNER_ID)
    mark_configured()
    yield
    reset_logged_out_owner()


def _runtime_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "runtime.db"
    prepare_test_database(
        db_path=db_path,
        busy_timeout_ms=BUSY_TIMEOUT_MS,
        migrations=load_default_migrations(),
    )
    return db_path


def _sign_in(
    db_path: Path,
    *,
    session_version: str = "1",
    access_token: str = "header.payload.signature",
) -> None:
    """The only state a background job is claimable in (design 6.2)."""
    import_desktop_session(
        db_path=db_path,
        busy_timeout_ms=BUSY_TIMEOUT_MS,
        user_id=USER_ID,
        desktop_access_token=access_token,
        expires_at="2099-03-22T01:00:00Z",
        session_version=session_version,
    )


def _suggestion_payload(job_id: str) -> SuggestionJobPayload:
    return {
        "job_id": job_id,
        "process_id": f"process-{job_id}",
        "suggestion_id": f"suggestion-{job_id}",
        "user_id": USER_ID,
        "insight_id": f"insight-{job_id}",
        "enqueued_at": "2026-03-22T00:00:01Z",
    }


def _enqueue_suggestion_job(db_path: Path, job_id: str) -> None:
    enqueue_local_job_with_connection(
        db_path=str(db_path),
        busy_timeout_ms=BUSY_TIMEOUT_MS,
        request=build_local_suggestion_enqueue_request(_suggestion_payload(job_id)),
    )


def _action_payload(job_id: str) -> ActionJobPayload:
    return build_action_job_payload(
        {
            "job_id": job_id,
            "process_id": f"process-{job_id}",
            "action_id": f"action-{job_id}",
            "user_id": USER_ID,
            "continuation_ref": {
                "kind": "user_step",
                "user_step_id": f"user-step-{job_id}",
            },
        }
    )


def _enqueue_action_job(db_path: Path, job_id: str) -> None:
    payload = _action_payload(job_id)
    insert_agent_action(
        db_path=db_path,
        user_id=USER_ID,
        suggestion_id=f"suggestion-{job_id}",
        action_id=payload["action_id"],
    )
    with sqlite3.connect(db_path) as connection:
        with connection:
            enqueue_local_job(
                connection=connection,
                request=build_local_action_enqueue_request(
                    payload,
                    scheduled_at="2026-03-22T00:00:01Z",
                    suggestion_id=f"suggestion-{job_id}",
                ),
            )


def _suggestion_specs(
    runner: Callable[[object], None],
) -> Mapping[str, LocalWorkerSpec]:
    default_specs = build_default_local_worker_specs(action_runner=lambda _: None)
    return {
        LOCAL_SUGGESTION_JOB_TYPE: replace(
            default_specs[LOCAL_SUGGESTION_JOB_TYPE], run=runner
        )
    }


def _read_job_state(db_path: Path, job_id: str) -> dict[str, object]:
    with sqlite3.connect(db_path) as connection:
        job_row = connection.execute(
            "SELECT status, claimed_by, error_code FROM jobs WHERE job_id = ?",
            (job_id,),
        ).fetchone()
        attempt_rows = connection.execute(
            "SELECT status, error_code FROM job_attempts WHERE job_id = ?",
            (job_id,),
        ).fetchall()
        process_row = connection.execute(
            "SELECT status, current_job_id FROM processes WHERE process_id = ?",
            (f"process-{job_id}",),
        ).fetchone()
    return {"job": job_row, "attempts": attempt_rows, "process": process_row}


def _record_llm_send_boundaries(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[CloudBoundary, SendBoundary]:
    """Record both LLM send boundaries, as `test_llm_route_decision` does."""
    cloud = CloudBoundary(
        _FakeHttpResponse(status_code=200, payload=CLOUD_RESPONSE_PAYLOAD)
    )
    cloud.install(monkeypatch)
    provider = SendBoundary(responder())
    monkeypatch.setattr(direct, "source_http_client", provider.http_client)
    return cloud, provider


async def _generate(contents: list[object]) -> None:
    """The entry every agent's LLM call goes through, file inputs included.

    The trace context is the one the executor bound for the claimed job.
    """
    await LocalLlmProxyClient(proxy_url=LLM_PROXY_URL).aio.models.generate_content(
        contents=contents,
        config=types.GenerateContentConfig(
            inference_profile=ACTIVITY_SUMMARY_PROFILE_ID
        ),
    )


async def _search() -> None:
    """The entry every agent's web search goes through."""
    context: WebToolsWrapperContext = {
        "user_id": USER_ID,
        "request_id": "request-1",
    }
    await invoke_web_tools_wrapper(
        tool_id="web_search",
        web_tool_profile=WEB_SEARCH_PROFILE_ID,
        args={"query": "Pantaray"},
        context=context,
        max_retries=1,
    )


def _make_claimable_now(db_path: Path, job_id: str) -> None:
    """Undo only the restart delay, so the requeued job can be claimed again."""
    with sqlite3.connect(db_path) as connection:
        with connection:
            connection.execute(
                "UPDATE jobs SET scheduled_at = '2026-03-22T00:00:01Z'"
                " WHERE job_id = ?",
                (job_id,),
            )


def test_a_background_job_returns_to_queued_and_runs_again(tmp_path: Path) -> None:
    db_path = _runtime_db(tmp_path)
    _sign_in(db_path)
    _enqueue_suggestion_job(db_path, "job-background")
    runs: list[str] = []

    def _run(payload: object) -> None:
        assert isinstance(payload, Mapping)
        runs.append(str(payload["job_id"]))
        if len(runs) == 1:
            # A second sign-in of the same account: a new cloud identity.
            _sign_in(db_path, session_version="2")
        asyncio.run(require_current_route_identity())

    executed = run_next_local_job(
        db_path=db_path,
        busy_timeout_ms=BUSY_TIMEOUT_MS,
        claimed_by=CLAIM_OWNER,
        specs=_suggestion_specs(_run),
    )

    assert executed is True
    state = _read_job_state(db_path, "job-background")
    assert state["job"] == ("queued", None, None)
    # No terminal row anywhere: the user never sees a failed Suggestion.
    assert state["attempts"] == [("completed", None)]
    assert state["process"] == ("enqueued", None)

    _make_claimable_now(db_path, "job-background")
    executed_again = run_next_local_job(
        db_path=db_path,
        busy_timeout_ms=BUSY_TIMEOUT_MS,
        claimed_by=CLAIM_OWNER,
        specs=_suggestion_specs(_run),
    )

    assert executed_again is True
    assert runs == ["job-background", "job-background"]
    state_after = _read_job_state(db_path, "job-background")
    assert state_after["job"] == ("completed", CLAIM_OWNER, None)
    assert state_after["process"] == ("success", None)


def test_an_action_is_not_requeued_when_its_route_changes(tmp_path: Path) -> None:
    db_path = _runtime_db(tmp_path)
    _sign_in(db_path)
    _enqueue_action_job(db_path, "job-action")

    def _run_action(_payload: object) -> None:
        _sign_in(db_path, session_version="2")
        asyncio.run(require_current_route_identity())

    with pytest.raises(LocalJobExecutionError) as raised:
        run_next_local_job(
            db_path=db_path,
            busy_timeout_ms=BUSY_TIMEOUT_MS,
            claimed_by=CLAIM_OWNER,
            specs={
                LOCAL_ACTION_JOB_TYPE: build_default_local_worker_specs(
                    action_runner=_run_action
                )[LOCAL_ACTION_JOB_TYPE]
            },
        )

    assert raised.value.original_exception_type == "LocalJobRouteIdentityChangedError"
    state = _read_job_state(db_path, "job-action")
    # The Stop fence the barrier recorded owns this run's terminal, so the
    # executor leaves the claim exactly as the Action left it.
    assert state["job"] == ("running", CLAIM_OWNER, None)
    assert state["attempts"] == [("running", None)]


def test_an_unchanged_identity_and_a_token_rotation_let_the_job_finish(
    tmp_path: Path,
) -> None:
    db_path = _runtime_db(tmp_path)
    _sign_in(db_path)
    set_llm_connection(
        ApiKeyConnection(provider="openai", model="gpt-5", api_key="key-1")
    )
    _enqueue_suggestion_job(db_path, "job-unchanged")

    def _run(_payload: object) -> None:
        asyncio.run(require_current_route_identity())
        # A Pantaray access-token refresh keeps the same sign-in (design 6.2).
        _sign_in(db_path, access_token="header.payload.rotated")
        asyncio.run(require_current_route_identity())
        # A direct connection is only stored while signed in, so replacing it
        # does not change what requests actually reach.
        set_llm_connection(
            ApiKeyConnection(provider="anthropic", model="claude", api_key="key-2")
        )
        asyncio.run(require_current_route_identity())

    executed = run_next_local_job(
        db_path=db_path,
        busy_timeout_ms=BUSY_TIMEOUT_MS,
        claimed_by=CLAIM_OWNER,
        specs=_suggestion_specs(_run),
    )

    assert executed is True
    state = _read_job_state(db_path, "job-unchanged")
    assert state["job"] == ("completed", CLAIM_OWNER, None)
    assert state["process"] == ("success", None)


def test_a_call_outside_a_claimed_job_does_nothing(tmp_path: Path) -> None:
    db_path = _runtime_db(tmp_path)
    _sign_in(db_path)

    asyncio.run(require_current_route_identity())
    _sign_in(db_path, session_version="2")

    asyncio.run(require_current_route_identity())


def test_the_binding_reaches_a_job_run_on_the_worker_thread_pool(
    tmp_path: Path,
) -> None:
    """The daemon claims on its own thread and runs the job on a pool thread."""
    db_path = _runtime_db(tmp_path)
    _sign_in(db_path)
    _enqueue_suggestion_job(db_path, "job-pool")

    def _run(_payload: object) -> None:
        _sign_in(db_path, session_version="2")
        asyncio.run(require_current_route_identity())

    spec = _suggestion_specs(_run)[LOCAL_SUGGESTION_JOB_TYPE]
    claimed_job = claim_next_pending_job(
        db_path=str(db_path),
        busy_timeout_ms=BUSY_TIMEOUT_MS,
        job_type=LOCAL_SUGGESTION_JOB_TYPE,
        owner_user_id=USER_ID,
        claimed_by=CLAIM_OWNER,
        process_running_status=spec.process_running_status,
        expected_process_pending_status=spec.process_pending_status,
    )
    assert claimed_job is not None
    capacity = LocalWorkerCapacity(
        max_running=1,
        job_type_limits={LOCAL_SUGGESTION_JOB_TYPE: 1},
    )
    lease = capacity.reserve(LOCAL_SUGGESTION_JOB_TYPE)
    with ThreadPoolExecutor(max_workers=1, thread_name_prefix="test-pool") as executor:
        executor.submit(
            worker_daemon._run_claimed_job_in_executor,
            db_path=db_path,
            busy_timeout_ms=BUSY_TIMEOUT_MS,
            claimed_job=claimed_job,
            spec=spec,
            capacity=capacity,
            lease=lease,
        ).result()

    # Requeued, not finalized: the run saw the identity its claim recorded.
    state = _read_job_state(db_path, "job-pool")
    assert state["job"] == ("queued", None, None)
    assert state["process"] == ("enqueued", None)


def test_the_llm_entry_sends_nothing_after_a_background_job_changes_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_path = _runtime_db(tmp_path)
    _sign_in(db_path)
    _enqueue_suggestion_job(db_path, "job-llm")
    cloud, provider = _record_llm_send_boundaries(monkeypatch)
    refuse_file_reads(monkeypatch)
    contents = file_contents(tmp_path)

    def _run(_payload: object) -> None:
        # A second sign-in of the same account: a new cloud identity.
        _sign_in(db_path, session_version="2")
        asyncio.run(_generate(contents))

    executed = run_next_local_job(
        db_path=db_path,
        busy_timeout_ms=BUSY_TIMEOUT_MS,
        claimed_by=CLAIM_OWNER,
        specs=_suggestion_specs(_run),
    )

    assert executed is True
    assert cloud.requests == []
    assert provider.requests == []
    state = _read_job_state(db_path, "job-llm")
    assert state["job"] == ("queued", None, None)
    assert state["attempts"] == [("completed", None)]
    assert state["process"] == ("enqueued", None)


def test_the_llm_entry_refuses_an_action_whose_identity_changed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_path = _runtime_db(tmp_path)
    _sign_in(db_path)
    _enqueue_action_job(db_path, "job-llm-action")
    cloud, provider = _record_llm_send_boundaries(monkeypatch)
    refuse_file_reads(monkeypatch)
    contents = file_contents(tmp_path)

    def _run_action(_payload: object) -> None:
        _sign_in(db_path, session_version="2")
        asyncio.run(_generate(contents))

    with pytest.raises(LocalJobExecutionError) as raised:
        run_next_local_job(
            db_path=db_path,
            busy_timeout_ms=BUSY_TIMEOUT_MS,
            claimed_by=CLAIM_OWNER,
            specs={
                LOCAL_ACTION_JOB_TYPE: build_default_local_worker_specs(
                    action_runner=_run_action
                )[LOCAL_ACTION_JOB_TYPE]
            },
        )

    assert raised.value.original_exception_type == "LocalJobRouteIdentityChangedError"
    assert cloud.requests == []
    assert provider.requests == []
    # Not requeued: the Stop fence the barrier recorded owns this terminal.
    assert _read_job_state(db_path, "job-llm-action")["job"] == (
        "running",
        CLAIM_OWNER,
        None,
    )


def test_the_web_search_entry_sends_nothing_after_the_identity_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_path = _runtime_db(tmp_path)
    _sign_in(db_path)
    _enqueue_suggestion_job(db_path, "job-web")
    proxy = _patch_proxy_transport(monkeypatch)
    tavily = _RecordingTavilyClient(result={})
    _patch_tavily(monkeypatch, tavily)

    def _run(_payload: object) -> None:
        _sign_in(db_path, session_version="2")
        asyncio.run(_search())

    executed = run_next_local_job(
        db_path=db_path,
        busy_timeout_ms=BUSY_TIMEOUT_MS,
        claimed_by=CLAIM_OWNER,
        specs=_suggestion_specs(_run),
    )

    assert executed is True
    assert proxy.post_count == 0
    assert tavily.calls == []
    state = _read_job_state(db_path, "job-web")
    assert state["job"] == ("queued", None, None)
    assert state["attempts"] == [("completed", None)]
    assert state["process"] == ("enqueued", None)


def test_a_finished_job_leaves_no_identity_behind_on_its_thread(
    tmp_path: Path,
) -> None:
    db_path = _runtime_db(tmp_path)
    _sign_in(db_path)
    _enqueue_suggestion_job(db_path, "job-released")

    executed = run_next_local_job(
        db_path=db_path,
        busy_timeout_ms=BUSY_TIMEOUT_MS,
        claimed_by=CLAIM_OWNER,
        specs=_suggestion_specs(lambda _payload: None),
    )
    assert executed is True

    _sign_in(db_path, session_version="2")
    asyncio.run(require_current_route_identity())

    state = _read_job_state(db_path, "job-released")
    assert state["job"] == ("completed", CLAIM_OWNER, None)
