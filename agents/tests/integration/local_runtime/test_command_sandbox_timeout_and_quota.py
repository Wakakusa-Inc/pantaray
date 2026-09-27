from __future__ import annotations

import asyncio
import os
import signal
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

from pantaray_agents.local_runtime.tooling.brokering import broker
from pantaray_agents.local_runtime.tooling.sandbox import command_sandbox_client
from pantaray_agents.local_runtime.tooling.sandbox.command_sandbox_protocol import (
    SandboxLifecycleEvent,
)
from pantaray_agents.local_runtime.tooling.sandbox.runtime_policy import (
    BrokerLocalBudget,
    RuntimeBudgetResolution,
    SandboxLaunchBudget,
)

from .support import (
    SEATBELT_SKIP_REASON,
    bootstrap_runtime_testbed,
    compile_workspace_binary,
    execute_bash,
    load_latest_audit,
    seatbelt_available,
)

pytestmark = pytest.mark.skipif(not seatbelt_available(), reason=SEATBELT_SKIP_REASON)


# The spill probe blocks until the temp-quota monitor kills it, so this timeout
# is only reached when quota enforcement is broken.
TEMP_QUOTA_BACKSTOP_TIMEOUT_MS = 10_000

SPILL_SOURCE = r"""
#include <stdio.h>
#include <stdlib.h>
#include <fcntl.h>
#include <string.h>
#include <unistd.h>

int main(void) {
    char path[4096];
    const char *tmpdir = getenv("TMPDIR");
    if (tmpdir == NULL) {
        return 2;
    }
    snprintf(path, sizeof(path), "%s/out.bin", tmpdir);
    int fd = open(path, O_CREAT | O_WRONLY | O_TRUNC, 0644);
    if (fd < 0) {
        return 3;
    }
    char buffer[4096];
    memset(buffer, 'a', sizeof(buffer));
    for (int index = 0; index < 32; ++index) {
        if (write(fd, buffer, sizeof(buffer)) != sizeof(buffer)) {
            close(fd);
            return 4;
        }
    }
    close(fd);
    pause();
    return 0;
}
"""


def _timeout_budget(*_, **__) -> RuntimeBudgetResolution:
    return RuntimeBudgetResolution(
        broker_local=BrokerLocalBudget(
            child_count_limit=8,
            open_file_lease_limit=8,
        ),
        sandbox_launch=SandboxLaunchBudget(
            timeout_ms=50,
            stdout_max_bytes=1_048_576,
            stderr_max_bytes=1_048_576,
            temp_storage_limit_bytes=1_048_576,
        ),
    )


def _temp_quota_budget(*_, **__) -> RuntimeBudgetResolution:
    return RuntimeBudgetResolution(
        broker_local=BrokerLocalBudget(
            child_count_limit=8,
            open_file_lease_limit=8,
        ),
        sandbox_launch=SandboxLaunchBudget(
            # The launch timeout must stay a far backstop, not a competing
            # deadline: it starts at sandbox-exec spawn, while the temp quota
            # can only be observed once the child has exec'd and written.
            timeout_ms=TEMP_QUOTA_BACKSTOP_TIMEOUT_MS,
            stdout_max_bytes=1_048_576,
            stderr_max_bytes=1_048_576,
            # Leave room for the OS profile; the child spills 128 KiB.
            temp_storage_limit_bytes=65_536,
        ),
    )


@pytest.mark.asyncio
async def test_timeout_is_terminalized_and_audited(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "pantaray_agents.local_runtime.tooling.brokering.broker_command_validation.resolve_runtime_budget",
        _timeout_budget,
    )
    testbed = bootstrap_runtime_testbed(tmp_path=tmp_path, monkeypatch=monkeypatch)
    outcome = await execute_bash(testbed=testbed, command="sleep 1")

    assert outcome.status == "error"
    assert outcome.output["stderr"] == ""
    assert "timed out after 50 ms" in outcome.output["error"]["message"]
    assert outcome.output["signal"] == signal.SIGKILL
    audit = load_latest_audit(db_path=testbed.db_path)
    assert audit["terminal_outcome"] == "timed_out"


@pytest.mark.asyncio
async def test_temp_quota_exceeded_is_terminalized_and_audited(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "pantaray_agents.local_runtime.tooling.brokering.broker_command_validation.resolve_runtime_budget",
        _temp_quota_budget,
    )
    testbed = bootstrap_runtime_testbed(tmp_path=tmp_path, monkeypatch=monkeypatch)
    compile_workspace_binary(
        workspace_path=testbed.context.workspace_path,
        executable_name="spillprobe",
        source_code=SPILL_SOURCE,
    )

    outcome = await execute_bash(testbed=testbed, command="spillprobe")

    assert outcome.status == "error"
    audit = load_latest_audit(db_path=testbed.db_path)
    assert audit["terminal_outcome"] == "budget_exceeded"
    assert audit["budget_exceeded_kind"] == "temp_storage_limit"


@pytest.mark.asyncio
@pytest.mark.parametrize("stream,fd", [("stdout", 1), ("stderr", 2)])
async def test_output_quota_stops_the_command_and_records_the_stream(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stream: str, fd: int
) -> None:
    base_budget = _temp_quota_budget()
    output_budget = replace(
        base_budget,
        sandbox_launch=replace(
            base_budget.sandbox_launch,
            stdout_max_bytes=4_096,
            stderr_max_bytes=4_096,
            temp_storage_limit_bytes=1_048_576,
        ),
    )
    monkeypatch.setattr(
        "pantaray_agents.local_runtime.tooling.brokering.broker_command_validation.resolve_runtime_budget",
        lambda **_: output_budget,
    )
    testbed = bootstrap_runtime_testbed(tmp_path=tmp_path, monkeypatch=monkeypatch)
    compile_workspace_binary(
        workspace_path=testbed.context.workspace_path,
        executable_name="outputprobe",
        source_code=f"""
#include <unistd.h>
int main(void) {{
    char buffer[4096] = {{0}};
    for (int i = 0; i < 512; ++i) {{
        if (write({fd}, buffer, sizeof(buffer)) < 0) return 1;
    }}
    pause();
    return 0;
}}
""",
    )
    outcome = await asyncio.wait_for(
        execute_bash(testbed=testbed, command="outputprobe"), timeout=20
    )

    assert outcome.status == "error"
    audit = load_latest_audit(db_path=testbed.db_path)
    assert audit["terminal_outcome"] == "budget_exceeded"
    assert audit["budget_exceeded_kind"] == f"{stream}_limit"
    assert audit[f"{stream}_bytes"] > audit[f"{stream}_max_bytes"]


async def _wait_for_sandboxed_child(helper_pid: int, *, timeout_s: float = 5.0) -> int:
    """The sandboxed process, once the OS lists it under the helper.

    The helper emits `started` right after its own spawn returns, so the child is
    moments old here and a single `pgrep` races that window.
    """
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_s
    while True:
        found = subprocess.run(
            ["pgrep", "-P", str(helper_pid)], capture_output=True, text=True
        ).stdout.split()
        if len(found) == 1:
            return int(found[0])
        if loop.time() >= deadline:
            raise AssertionError(
                f"helper {helper_pid} should own one sandboxed child, saw {found}"
            )
        await asyncio.sleep(0.05)


@pytest.mark.asyncio
async def test_stop_reaps_the_real_sleep_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    testbed = bootstrap_runtime_testbed(tmp_path=tmp_path, monkeypatch=monkeypatch)
    started = asyncio.Event()
    helper: asyncio.subprocess.Process | None = None
    child_pid: int | None = None
    spawn = broker.asyncio.create_subprocess_exec
    messages = command_sandbox_client.iter_decoded_messages

    async def capture_helper(*args, **kwargs):
        nonlocal helper
        helper = await spawn(*args, **kwargs)
        return helper

    async def observe_start(stream):
        async for message in messages(stream):
            if (
                isinstance(message, SandboxLifecycleEvent)
                and message.event == "started"
            ):
                started.set()
            yield message

    monkeypatch.setattr(broker.asyncio, "create_subprocess_exec", capture_helper)
    monkeypatch.setattr(command_sandbox_client, "iter_decoded_messages", observe_start)
    task = asyncio.create_task(execute_bash(testbed=testbed, command="sleep 5"))
    try:
        await asyncio.wait_for(started.wait(), timeout=10)
        assert helper is not None
        child_pid = await _wait_for_sandboxed_child(helper.pid)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, timeout=3)
        with pytest.raises(ProcessLookupError):
            os.kill(child_pid, 0)
        assert (
            load_latest_audit(db_path=testbed.db_path)["terminal_outcome"] == "canceled"
        )
    finally:
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        # Reap the probe even when a regression leaves it alive after Stop.
        if child_pid is not None:
            try:
                os.kill(child_pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
