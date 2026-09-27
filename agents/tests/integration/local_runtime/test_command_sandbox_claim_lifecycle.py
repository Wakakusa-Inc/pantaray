from __future__ import annotations

import asyncio
import multiprocessing
import signal
import sqlite3
import time
from pathlib import Path

import pytest
from tests.unit.local_runtime.broker_test_support import (
    BROKER_ACTOR_PROCESS_ID,
    _seed_broker_actor_process,
)

from pantaray_agents.local_runtime.storage.migrations.connection import (
    configure_connection,
)
from pantaray_agents.local_runtime.storage.transactions import immediate_transaction
from pantaray_agents.local_runtime.tooling.action_subagent_resource_claims import (
    ActionSubagentResourceClaimConflictError,
    WorkspacePathResourceClaim,
    acquire_action_subagent_resource_claims_in_connection,
)
from pantaray_agents.local_runtime.tooling.resources.resource_cleanup import (
    process_exists,
)
from pantaray_agents.local_runtime.tooling.resources.resource_recovery import (
    reconcile_tool_runtime_resources_for_startup,
)

from .support import (
    SEATBELT_SKIP_REASON,
    RuntimeIntegrationTestbed,
    bootstrap_runtime_testbed,
    execute_bash,
    seatbelt_available,
)

pytestmark = pytest.mark.skipif(not seatbelt_available(), reason=SEATBELT_SKIP_REASON)


def _run_backend(testbed: RuntimeIntegrationTestbed) -> None:
    outcome = asyncio.run(
        execute_bash(
            testbed=testbed,
            command=(
                "sleep 60 >/dev/null 2>&1 & echo $! > background.pid; "
                "printf ready > ready; "
                "while [ ! -e release ]; do sleep 0.05; done; "
                "printf written > claimed/value.txt"
            ),
        )
    )
    assert outcome.status == "success", outcome


def _acquire_claim(testbed: RuntimeIntegrationTestbed, action_id: str) -> None:
    with sqlite3.connect(testbed.db_path) as connection:
        configure_connection(connection, 1_000)
        connection.row_factory = sqlite3.Row
        with immediate_transaction(connection):
            acquire_action_subagent_resource_claims_in_connection(
                connection,
                user_id="user-1",
                action_id=action_id,
                parent_process_id=BROKER_ACTOR_PROCESS_ID,
                child_process_id="claim-child",
                acquired_at="2026-09-11T00:00:00Z",
                claims=(
                    WorkspacePathResourceClaim(
                        claim_id="claim-transfer",
                        manifest_id=testbed.context.manifest_id,
                        raw_path="claimed",
                        current_cwd=testbed.context.workspace_path,
                    ),
                ),
            )


@pytest.mark.parametrize("backend_crash", [False, True])
def test_claim_transfer_waits_for_real_command_and_background_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    backend_crash: bool,
) -> None:
    testbed = bootstrap_runtime_testbed(tmp_path=tmp_path, monkeypatch=monkeypatch)
    root = testbed.context.workspace_path
    (root / "claimed").mkdir()
    with sqlite3.connect(testbed.db_path) as connection:
        action_id = str(
            connection.execute(
                "SELECT action_id FROM processes WHERE process_id = ?",
                (BROKER_ACTOR_PROCESS_ID,),
            ).fetchone()[0]
        )
    _seed_broker_actor_process(
        testbed.db_path,
        process_id="claim-child",
        action_id=action_id,
        kind="action_subagent",
        parent_process_id=BROKER_ACTOR_PROCESS_ID,
    )
    # The fork inherits only this test's isolated configuration and database.
    backend = multiprocessing.get_context("fork").Process(
        target=_run_backend, args=(testbed,)
    )
    backend.start()
    try:
        deadline = time.monotonic() + 15
        while not (root / "ready").exists():
            assert backend.is_alive(), f"backend ended before ready: {backend.exitcode}"
            assert time.monotonic() < deadline, "command never reached ready barrier"
            time.sleep(0.05)
        background_pid = int((root / "background.pid").read_text())
        assert process_exists(pid=background_pid)
        with pytest.raises(ActionSubagentResourceClaimConflictError):
            _acquire_claim(testbed, action_id)
        if backend_crash:
            backend.kill()
            backend.join(timeout=5)
            assert backend.exitcode == -signal.SIGKILL
            with pytest.raises(ActionSubagentResourceClaimConflictError):
                _acquire_claim(testbed, action_id)
            reconcile_tool_runtime_resources_for_startup(
                db_path=testbed.db_path, busy_timeout_ms=1_000
            )
            assert not (root / "claimed/value.txt").exists()
        else:
            (root / "release").touch()
            backend.join(timeout=15)
            assert backend.exitcode == 0
            assert (root / "claimed/value.txt").read_text() == "written"
        assert not process_exists(pid=background_pid)
        _acquire_claim(testbed, action_id)
        with sqlite3.connect(testbed.db_path) as connection:
            assert connection.execute(
                "SELECT status FROM tool_runtime_resources WHERE resource_kind = 'process_group'"
            ).fetchall() == [("cleaned",)]
    finally:
        if backend.is_alive():
            backend.kill()
            backend.join(timeout=5)
        reconcile_tool_runtime_resources_for_startup(
            db_path=testbed.db_path, busy_timeout_ms=1_000
        )
        backend.close()
