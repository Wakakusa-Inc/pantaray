from __future__ import annotations

import asyncio
import os
import shlex
import signal
import socket
import subprocess
import sys
from contextlib import closing
from pathlib import Path

import pytest

from pantaray_agents.local_runtime.tooling.repository.command_network_settings import (
    update_command_network_enabled,
)

from .support import (
    SEATBELT_SKIP_REASON,
    bootstrap_runtime_testbed,
    execute_bash,
    seatbelt_available,
)

pytestmark = pytest.mark.skipif(not seatbelt_available(), reason=SEATBELT_SKIP_REASON)


@pytest.mark.asyncio
async def test_venv_runs_from_subdirectory_with_system_name_resolution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    testbed = bootstrap_runtime_testbed(tmp_path=tmp_path, monkeypatch=monkeypatch)
    workspace = testbed.context.workspace_path
    (workspace / "tests").mkdir()
    (workspace / "tests/probe.py").write_text(
        "import ipaddress, pathlib, socket, sys\n"
        "assert sys.prefix != sys.base_prefix\n"
        "addresses = socket.getaddrinfo('localhost', 443, type=socket.SOCK_STREAM)\n"
        "assert addresses\n"
        "assert all(ipaddress.ip_address(row[4][0]).is_loopback for row in addresses)\n"
        "pathlib.Path('result.txt').write_text('venv ok')\n"
    )
    outcome = await execute_bash(
        testbed=testbed,
        command=(
            f"{shlex.quote(str(Path(sys.executable).resolve()))} -m venv .venv && "
            "cd tests && ../.venv/bin/python probe.py"
        ),
    )
    assert outcome.status == "success", outcome.output
    assert (workspace / "tests/result.txt").read_text() == "venv ok"


@pytest.mark.asyncio
@pytest.mark.parametrize("enabled", [True, False])
async def test_git_clone_and_push_obey_command_network_setting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, enabled: bool
) -> None:
    testbed = bootstrap_runtime_testbed(tmp_path=tmp_path, monkeypatch=monkeypatch)
    if not enabled:
        update_command_network_enabled(
            db_path=testbed.db_path,
            busy_timeout_ms=1_000,
            user_id="user-1",
            command_network_enabled=False,
            now="2026-09-11T00:00:00Z",
        )
    remote = tmp_path / "remote.git"
    git_env = {
        **os.environ,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
    }
    subprocess.run(
        ["git", "init", "--bare", str(remote)],
        env=git_env,
        check=True,
        capture_output=True,
    )
    with closing(socket.socket()) as reserved:
        reserved.bind(("127.0.0.1", 0))
        port = reserved.getsockname()[1]
    daemon = await asyncio.create_subprocess_exec(
        "git",
        "daemon",
        "--verbose",
        "--export-all",
        "--enable=receive-pack",
        "--listen=127.0.0.1",
        f"--port={port}",
        f"--base-path={tmp_path}",
        env=git_env,
        start_new_session=True,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        assert daemon.stderr is not None
        ready = await asyncio.wait_for(daemon.stderr.readline(), timeout=5)
        assert b"Ready to rumble" in ready, ready
        outcome = await execute_bash(
            testbed=testbed,
            command=(
                f"git clone git://127.0.0.1:{port}/remote.git clone && cd clone && "
                "printf 'transferred' > result.txt && git add result.txt && "
                "git -c user.name=Sandbox -c user.email=sandbox@example.invalid commit -m probe && "
                "git push origin HEAD:refs/heads/main"
            ),
        )
        assert outcome.status == ("success" if enabled else "error"), outcome.output
        stored = subprocess.run(
            ["git", "--git-dir", str(remote), "show", "refs/heads/main:result.txt"],
            env=git_env,
            text=True,
            capture_output=True,
            check=False,
        )
        if enabled:
            assert stored.returncode == 0, stored.stderr
            assert stored.stdout == "transferred"
        else:
            assert stored.returncode != 0
    finally:
        if daemon.returncode is None:
            os.killpg(daemon.pid, signal.SIGKILL)
        await daemon.wait()
