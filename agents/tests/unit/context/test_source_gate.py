import asyncio
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from dataclasses import replace
from threading import Event
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from pantaray_agents import auth_http
from pantaray_agents.local_runtime.context import store
from pantaray_agents.local_runtime.context.source_control import SourceControl
from pantaray_agents.local_runtime.context.source_gate import (
    SourceGate,
    SourceInvalidated,
)
from pantaray_agents.local_runtime.memory_catalog.connection import (
    open_memory_catalog_connection,
)
from pantaray_agents.local_runtime.runtime import identity
from pantaray_agents.local_runtime.runtime.local_api_auth import (
    authenticate_local_api_request,
)
from pantaray_agents.local_runtime.storage.migrations import (
    apply_migrations,
    load_default_migrations,
)
from pantaray_agents.routers import context_source
from pantaray_agents.schema.context_source import (
    ActivateSource,
    RecorderBinding,
    SetCapturePaused,
    SuspendSource,
)


@pytest.fixture
def database(tmp_path, monkeypatch):
    path = tmp_path / "runtime.db"
    apply_migrations(path, 1000, load_default_migrations())
    monkeypatch.setattr(
        identity,
        "current_owner_id",
        lambda: "alice",
    )
    with open_memory_catalog_connection(db_path=path, busy_timeout_ms=1000) as conn:
        conn.executemany(
            "INSERT INTO users VALUES (?, 'ja', NULL, 'now', 'now')",
            [("alice",), ("bob",)],
        )
        conn.commit()
        yield path, conn


def suspend(epoch=UUID(int=0), **changes):
    return SuspendSource(
        kind="suspend",
        request_id=uuid4(),
        expected_epoch=epoch,
        policy_revision="policy",
        reason="policy_change",
    ).model_copy(update=changes)


def activate(epoch, paused=False):
    return ActivateSource(
        kind="activate",
        request_id=uuid4(),
        issued_epoch=epoch,
        recorder_binding=RecorderBinding(store_id="store", protocol_version=1),
        capture_paused=paused,
    )


def set_capture_paused(epoch, paused):
    return SetCapturePaused(
        kind="set_capture_paused",
        request_id=uuid4(),
        expected_epoch=epoch,
        paused=paused,
    )


async def ready(control, conn):
    request = suspend()
    stopped = await control.transition(conn, "alice", request)
    activation = activate(stopped.state.epoch)
    result = await control.transition(conn, "alice", activation)
    async with control.gate.turn():
        permit = control.gate.current("alice")
    assert permit is not None
    return permit, request, activation, result


@pytest.mark.asyncio
async def test_readonly_and_historical_replay_cannot_restore_permit(database):
    _, conn = database
    control = SourceControl()
    before = conn.total_changes
    assert (await control.read(conn, "alice")).epoch == UUID(int=0)
    assert conn.total_changes == before and store.get_source(conn, "alice") is None
    permit, initial, activation, applied = await ready(control, conn)
    stopped = await control.transition(
        conn,
        "alice",
        suspend(permit.binding.epoch, policy_revision="new", reason="signed_out"),
    )
    await control.transition(conn, "alice", activate(stopped.state.epoch))
    async with control.gate.turn():
        current = control.gate.current("alice")
    assert await control.transition(conn, "alice", activation) == applied
    assert (
        await control.transition(conn, "alice", initial)
    ).state.epoch == permit.binding.epoch
    assert (await control.read(conn, "alice")).binding == current.binding
    async with control.gate.guard(current):
        assert current.binding.policy_revision == "new"
    for invalid in [permit, replace(current, token=uuid4())] + [
        replace(current, binding=current.binding.model_copy(update={field: value}))
        for field, value in [
            ("user_id", "bob"),
            ("store_id", "other"),
            ("policy_revision", "old"),
            ("epoch", uuid4()),
        ]
    ]:
        with pytest.raises(SourceInvalidated):
            async with control.gate.guard(invalid):
                pytest.fail("invalid read/publication was admitted")


@pytest.mark.asyncio
async def test_reused_id_stale_transition_and_restart(database):
    _, conn = database
    control = SourceControl()
    permit, initial, activation, applied = await ready(control, conn)
    reused = await control.transition(
        conn, "alice", initial.model_copy(update={"policy_revision": "other"})
    )
    assert reused.reason == "request_id_reused"
    for request in (suspend(), activate(uuid4())):
        conflict = await control.transition(conn, "alice", request)
        assert conflict.reason == "stale_epoch"
        assert await control.transition(conn, "alice", request) == conflict
    restarted = SourceControl()
    before = conn.total_changes
    state = await restarted.read(conn, "alice")
    assert state.reason == "shutdown" and state.epoch == permit.binding.epoch
    assert conn.total_changes == before
    assert (
        await restarted.transition(conn, "alice", activate(state.epoch))
    ).state.reason == "recorder_unavailable"
    assert await restarted.transition(conn, "alice", activation) == applied
    assert (await restarted.read(conn, "alice")).kind == "stopped"
    stopped = await restarted.transition(conn, "alice", suspend(state.epoch))
    assert (
        await restarted.transition(conn, "alice", activate(stopped.state.epoch))
    ).state.kind == "ready"


@pytest.mark.asyncio
async def test_pausing_capture_keeps_the_permit_and_its_running_reads(database):
    """Recording turned off must keep reads of what was already recorded working."""
    _, conn = database
    control = SourceControl()
    permit, _, _, _ = await ready(control, conn)
    entered = asyncio.Event()
    release = asyncio.Event()

    async def read_in_flight():
        async with control.gate.track(permit):
            entered.set()
            await release.wait()

    task = asyncio.create_task(read_in_flight())
    await entered.wait()
    request = set_capture_paused(permit.binding.epoch, True)
    paused = await control.transition(conn, "alice", request)
    assert paused.state.capture_paused is True
    assert paused.state.binding == permit.binding
    assert await control.transition(conn, "alice", request) == paused
    assert (await control.read(conn, "alice")).capture_paused is True
    async with control.gate.turn():
        assert control.gate.current("alice") == permit
    async with control.gate.guard(permit):
        pass
    release.set()
    await task
    resumed = await control.transition(
        conn, "alice", set_capture_paused(permit.binding.epoch, False)
    )
    assert resumed.state.capture_paused is False
    async with control.gate.turn():
        assert control.gate.current("alice") == permit


@pytest.mark.asyncio
async def test_restoring_a_paused_recorder_is_never_readable_as_capturing(database):
    """A recorder restored for a user who has recording off becomes ready paused.

    The local workers run concurrently, so a Suggestion job queued before the
    restart can read the source at any moment. Publishing readiness first and the
    pause afterwards would leave a window in which it reads recording as on.
    """
    _, conn = database
    control = SourceControl()
    stopped = await control.transition(conn, "alice", suspend())
    applied = await control.transition(
        conn, "alice", activate(stopped.state.epoch, paused=True)
    )
    assert applied.state.capture_paused is True
    # The workers read the committed source, not the permit, and the very first
    # state this activation makes visible already says recording is off.
    assert store.is_capture_paused(conn, "alice") is True
    # The permit still comes with it: reads of what the recorder already stored
    # are the reason an off recorder is restored at all.
    async with control.gate.turn():
        assert control.gate.current("alice") is not None
    assert (await control.read(conn, "alice")).capture_paused is True


@pytest.mark.asyncio
async def test_capture_pause_needs_the_current_running_source(database):
    _, conn = database
    control = SourceControl()
    permit, _, _, _ = await ready(control, conn)
    stale = await control.transition(conn, "alice", set_capture_paused(uuid4(), True))
    assert stale.reason == "stale_epoch"
    stopped = await control.transition(conn, "alice", suspend(permit.binding.epoch))
    blocked = await control.transition(
        conn, "alice", set_capture_paused(stopped.state.epoch, True)
    )
    assert blocked.state.reason == "recorder_unavailable"
    assert (await control.read(conn, "alice")).kind == "stopped"


@pytest.mark.asyncio
async def test_commit_failure_rolls_back_receipt_state_and_permit(database):
    _, conn = database
    control = SourceControl()
    permit, _, _, applied = await ready(control, conn)
    # Deferred FK fails COMMIT after both normal writes have succeeded.
    conn.executescript("""CREATE TABLE commit_parent (id INTEGER PRIMARY KEY);
        CREATE TABLE commit_child (id INTEGER REFERENCES commit_parent(id) DEFERRABLE INITIALLY DEFERRED);
        CREATE TRIGGER fail_commit AFTER UPDATE ON context_sources BEGIN
          INSERT INTO commit_child VALUES (1); END;""")
    request = suspend(permit.binding.epoch)
    with pytest.raises(sqlite3.IntegrityError):
        await control.transition(conn, "alice", request)
    assert not conn.in_transaction
    assert store.get_source(conn, "alice") == applied.state
    assert store.get_source_receipt(conn, "alice", request) is None
    async with control.gate.guard(permit):
        pass
    conn.execute("DROP TRIGGER fail_commit")
    assert (await control.transition(conn, "alice", request)).kind == "applied"


@pytest.mark.asyncio
async def test_sign_out_cancels_old_response_preserves_new_permit(database):
    _, conn = database
    control = SourceControl()
    permit, _, _, _ = await ready(control, conn)
    entered = asyncio.Event()

    async def response_wait():
        async with control.gate.track(permit):
            entered.set()
            await asyncio.Event().wait()

    task = asyncio.create_task(response_wait())
    await entered.wait()
    stopped = await control.transition(
        conn, "alice", suspend(permit.binding.epoch, reason="signed_out")
    )
    await control.transition(conn, "alice", activate(stopped.state.epoch))
    with pytest.raises(asyncio.CancelledError):
        await task
    async with control.gate.turn():
        current = control.gate.current("alice")
    async with control.gate.guard(current):
        pass


@pytest.mark.asyncio
@pytest.mark.parametrize("reason", ["policy_change", "shutdown", "disabled"])
async def test_recorder_restart_preserves_reads_and_advances_control_epoch(
    database, reason
):
    _, conn = database
    control = SourceControl()
    permit, _, _, _ = await ready(control, conn)
    entered, release = asyncio.Event(), asyncio.Event()

    async def read_in_flight():
        async with control.gate.track(permit):
            entered.set()
            await release.wait()
            async with control.gate.guard(permit):
                return "recorded context"

    task = asyncio.create_task(read_in_flight())
    try:
        await entered.wait()
        stopped = await control.transition(
            conn,
            "alice",
            suspend(permit.binding.epoch, reason=reason, policy_revision="new"),
        )
        # A recorder can stay down while the settings dialog remains open.
        async with control.gate.guard(permit):
            pass
        restarted = await control.transition(
            conn, "alice", activate(stopped.state.epoch, paused=reason == "disabled")
        )
        assert (await control.read(conn, "alice")) == restarted.state
        assert restarted.state.binding.epoch != permit.binding.epoch
        assert restarted.state.binding.policy_revision == "new"
        assert store.is_capture_paused(conn, "alice") == (reason == "disabled")
        # Replaying the old control generation still cannot change the recorder.
        conflict = await control.transition(
            conn, "alice", suspend(permit.binding.epoch)
        )
        assert conflict.reason == "stale_epoch"
        release.set()
        assert await task == "recorded context"
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["store", "session"])
async def test_store_replacement_or_session_loss_revokes_retained_reads(
    database, change
):
    _, conn = database
    control = SourceControl()
    permit, _, _, _ = await ready(control, conn)
    entered = asyncio.Event()

    async def response_wait():
        async with control.gate.track(permit):
            entered.set()
            await asyncio.Event().wait()

    task = asyncio.create_task(response_wait())
    try:
        await entered.wait()
        stopped = await control.transition(
            conn, "alice", suspend(permit.binding.epoch, reason="shutdown")
        )
        if change == "store":
            request = activate(stopped.state.epoch).model_copy(
                update={
                    "recorder_binding": RecorderBinding(
                        store_id="other", protocol_version=1
                    )
                }
            )
            await control.transition(conn, "alice", request)
        else:
            async with control.gate.turn():
                control.forget_session("alice")
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 2)
        with pytest.raises(SourceInvalidated):
            async with control.gate.guard(permit):
                pytest.fail("old context access survived a store or session change")
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_cancelled_holder_releases_gate():
    gate = SourceGate()
    entered = asyncio.Event()

    async def hold():
        async with gate.turn():
            entered.set()
            await asyncio.Event().wait()

    task = asyncio.create_task(hold())
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    async with asyncio.timeout(2), gate.turn():
        pass


def test_cross_loop_cancelled_waiter_cannot_overtake_holder():
    gate = SourceGate()
    entered, release = Event(), Event()
    order = []

    def first_loop():
        async def run():
            async with gate.turn():
                order.append("send-start")
                entered.set()
                await asyncio.to_thread(release.wait)
                order.append("headers-written")

        asyncio.run(run())

    async def next_loop():
        async def queued():
            async with gate.turn():
                pytest.fail("cancelled waiter entered")

        task = asyncio.create_task(queued())
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        async def suspend_turn():
            async with gate.turn():
                order.append("suspend")

        waiter = asyncio.create_task(suspend_turn())
        await asyncio.sleep(0)
        assert not waiter.done()
        release.set()
        await asyncio.wait_for(waiter, 2)

    with ThreadPoolExecutor(max_workers=1) as pool:
        holder = pool.submit(first_loop)
        try:
            assert entered.wait(2)
            asyncio.run(next_loop())
        finally:
            release.set()
        holder.result(timeout=2)
    assert order == ["send-start", "headers-written", "suspend"]


def test_cross_loop_sign_out_cancels_tracked_work(database):
    _, conn = database
    control = SourceControl()
    permit, _, _, _ = asyncio.run(ready(control, conn))
    entered = Event()

    async def worker():
        with pytest.raises(asyncio.CancelledError):
            async with control.gate.track(permit):
                entered.set()
                await asyncio.wait_for(asyncio.Event().wait(), 2)

    with ThreadPoolExecutor(max_workers=1) as pool:
        result = pool.submit(asyncio.run, worker())
        assert entered.wait(2)
        asyncio.run(
            control.transition(
                conn, "alice", suspend(permit.binding.epoch, reason="signed_out")
            )
        )
        result.result(timeout=3)


def test_routes_auth_subject_wire_replay(database, monkeypatch):
    path, conn = database

    @asynccontextmanager
    async def lifespan(app):
        app.state.authenticate_request = authenticate_local_api_request
        yield

    app = FastAPI(lifespan=lifespan)
    app.include_router(context_source.router)
    monkeypatch.setattr(context_source, "context_source_control", SourceControl())
    monkeypatch.setattr(
        context_source, "read_local_runtime_db_config", lambda: (path, 1000)
    )
    endpoint = "/v1/agents/users/alice/context-source"
    with TestClient(app) as client:
        assert client.get(endpoint).status_code == 401
        assert (
            client.post(
                endpoint + "/transitions", json=suspend().model_dump(mode="json")
            ).status_code
            == 401
        )
        app.dependency_overrides[auth_http.get_current_user_id_from_token] = lambda: (
            "bob"
        )
        assert client.get(endpoint).status_code == 403
        app.dependency_overrides[auth_http.get_current_user_id_from_token] = lambda: (
            "alice"
        )
        assert client.get(endpoint).json()["epoch"] == str(UUID(int=0))
        invalid = suspend().model_dump(mode="json") | {"executable": "/tmp/arbitrary"}
        assert client.post(endpoint + "/transitions", json=invalid).status_code == 422
        request = suspend().model_dump(mode="json")
        response = client.post(endpoint + "/transitions", json=request)
        assert response.status_code == 200 and response.json()["kind"] == "applied"
        assert (
            client.post(endpoint + "/transitions", json=request).json()
            == response.json()
        )
        assert store.get_source(conn, "bob") is None
        monkeypatch.setattr(identity, "current_owner_id", lambda: "bob")
        assert client.get(endpoint).status_code == 403
        assert client.post(endpoint + "/transitions", json=request).status_code == 403


@pytest.mark.asyncio
async def test_nested_tracking_keeps_outer_operation_cancellable(database):
    _, conn = database
    control = SourceControl()
    permit, _, _, _ = await ready(control, conn)
    entered = asyncio.Event()

    async def work():
        async with control.gate.track(permit):
            async with control.gate.track(permit):
                pass
            entered.set()
            await asyncio.Event().wait()

    task = asyncio.create_task(work())
    await entered.wait()
    await control.transition(
        conn, "alice", suspend(permit.binding.epoch, reason="signed_out")
    )
    with pytest.raises(asyncio.CancelledError):
        await task


def test_delayed_cancel_does_not_cancel_next_operation_in_same_task(database):
    _, conn = database
    control = SourceControl()
    permit, _, _, _ = asyncio.run(ready(control, conn))
    entered, revoked = Event(), Event()

    async def worker():
        async with control.gate.track(permit):
            entered.set()
            # Hold this worker loop so the cancel callback arrives after exit.
            assert revoked.wait(2)
        await asyncio.sleep(0)
        return "next operation survived"

    with ThreadPoolExecutor(max_workers=1) as pool:
        task = pool.submit(asyncio.run, worker())
        try:
            assert entered.wait(2)
            asyncio.run(
                control.transition(
                    conn, "alice", suspend(permit.binding.epoch, reason="signed_out")
                )
            )
        finally:
            revoked.set()
        assert task.result(timeout=2) == "next operation survived"


@pytest.mark.asyncio
async def test_failed_activation_keeps_issued_epoch_for_retry(database):
    _, conn = database
    control = SourceControl()
    stopped = await control.transition(conn, "alice", suspend())
    request = activate(stopped.state.epoch)
    conn.executescript("""CREATE TABLE commit_parent (id INTEGER PRIMARY KEY);
        CREATE TABLE commit_child (id INTEGER REFERENCES commit_parent(id) DEFERRABLE INITIALLY DEFERRED);
        CREATE TRIGGER fail_commit AFTER UPDATE ON context_sources BEGIN
          INSERT INTO commit_child VALUES (1); END;""")
    with pytest.raises(sqlite3.IntegrityError):
        await control.transition(conn, "alice", request)
    assert await control.read(conn, "alice") == stopped.state
    async with control.gate.turn():
        assert control.gate.current("alice") is None
    conn.execute("DROP TRIGGER fail_commit")
    assert (await control.transition(conn, "alice", request)).state.kind == "ready"


@pytest.mark.asyncio
async def test_cancellation_burst_does_not_strand_control(database):
    _, conn = database
    control = SourceControl()
    # Exceeds the synchronous Future callback recursion depth of a tail chain.
    async with control.gate.turn():
        waiters = [
            asyncio.create_task(control.read(conn, "alice")) for _ in range(1500)
        ]
        await asyncio.sleep(0)
        for waiter in waiters:
            waiter.cancel()
        results = await asyncio.gather(*waiters, return_exceptions=True)
        assert all(isinstance(result, asyncio.CancelledError) for result in results)
    async with asyncio.timeout(2):
        assert (await control.transition(conn, "alice", suspend())).kind == "applied"
