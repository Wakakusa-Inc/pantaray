from __future__ import annotations

from pathlib import Path

import pytest

from pantaray_agents.local_runtime.tooling.brokering import broker as broker_module
from pantaray_agents.local_runtime.tooling.brokering.broker import BrokerExecutionError

from .support import (
    SEATBELT_SKIP_REASON,
    bootstrap_runtime_testbed,
    compile_workspace_binary,
    execute_bash,
    load_latest_temp_resource,
    seatbelt_available,
)

pytestmark = pytest.mark.skipif(not seatbelt_available(), reason=SEATBELT_SKIP_REASON)


PWD_SOURCE = r"""
#include <stdio.h>

int main(void) {
    puts("ok");
    return 0;
}
"""


@pytest.mark.asyncio
async def test_helper_spawn_failure_cleans_invocation_temp_dir(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    testbed = bootstrap_runtime_testbed(tmp_path=tmp_path, monkeypatch=monkeypatch)
    compile_workspace_binary(
        workspace_path=testbed.context.workspace_path,
        executable_name="cleanprobe",
        source_code=PWD_SOURCE,
    )

    async def _failing_create_subprocess_exec(*args, **kwargs):
        del args, kwargs
        raise RuntimeError("spawn failed")

    monkeypatch.setattr(
        broker_module.asyncio,
        "create_subprocess_exec",
        _failing_create_subprocess_exec,
    )

    with pytest.raises(RuntimeError, match="spawn failed"):
        await execute_bash(testbed=testbed, command="cleanprobe")

    resource = load_latest_temp_resource(db_path=testbed.db_path)
    assert resource["status"] == "cleaned"
    assert not Path(str(resource["resource_path"])).exists()


@pytest.mark.asyncio
async def test_process_group_registration_failure_cleans_invocation_temp_dir(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    testbed = bootstrap_runtime_testbed(tmp_path=tmp_path, monkeypatch=monkeypatch)
    compile_workspace_binary(
        workspace_path=testbed.context.workspace_path,
        executable_name="cleanprobe",
        source_code=PWD_SOURCE,
    )

    class _FakeStdout:
        async def readline(self) -> bytes:
            return b""

    class _FakeStderr:
        async def read(self) -> bytes:
            return b""

    class _FakeStdin:
        def write(self, data: bytes) -> None:
            del data

        async def drain(self) -> None:
            return None

        def close(self) -> None:
            return None

    class _FakeProcess:
        pid = 4321
        returncode = 0

        def __init__(self) -> None:
            self.stdin = _FakeStdin()
            self.stdout = _FakeStdout()
            self.stderr = _FakeStderr()

        async def wait(self) -> int:
            return self.returncode

    async def _fake_create_subprocess_exec(*args, **kwargs):
        del args, kwargs
        return _FakeProcess()

    def _failing_register_process_group_resource(**kwargs):
        del kwargs
        raise RuntimeError("resource registration failed")

    monkeypatch.setattr(
        broker_module.asyncio,
        "create_subprocess_exec",
        _fake_create_subprocess_exec,
    )
    monkeypatch.setattr(
        broker_module,
        "register_process_group_resource",
        _failing_register_process_group_resource,
    )

    with pytest.raises(
        BrokerExecutionError,
        match="failed to register command sandbox cleanup resource",
    ):
        await execute_bash(testbed=testbed, command="cleanprobe")

    resource = load_latest_temp_resource(db_path=testbed.db_path)
    assert resource["status"] == "cleaned"
    assert not Path(str(resource["resource_path"])).exists()
