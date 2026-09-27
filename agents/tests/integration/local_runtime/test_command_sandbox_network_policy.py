from __future__ import annotations

import socket
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path

import pytest
from tests.unit.local_runtime.broker_test_support import _register_folder_mount

from pantaray_agents.local_runtime.tooling.repository.command_network_settings import (
    update_command_network_enabled,
)

from .support import (
    SEATBELT_SKIP_REASON,
    bootstrap_runtime_testbed,
    compile_workspace_binary,
    execute_bash,
    seatbelt_available,
    start_tcp_probe_server,
)

pytestmark = pytest.mark.skipif(not seatbelt_available(), reason=SEATBELT_SKIP_REASON)

CONNECT_SOURCE = r"""
#include <arpa/inet.h>
#include <stdio.h>
#include <sys/socket.h>
#include <unistd.h>
int main(void) {
    int fd = socket(AF_INET, SOCK_STREAM, 0);
    if (fd < 0) { perror("socket"); return 2; }
    struct sockaddr_in address = {0};
    address.sin_family = AF_INET;
    address.sin_port = htons(__PORT__);
    inet_pton(AF_INET, "127.0.0.1", &address.sin_addr);
    if (connect(fd, (struct sockaddr *)&address, sizeof(address)) != 0) {
        perror("connect"); close(fd); return 111;
    }
    write(fd, "connected", 9);
    close(fd);
    return 0;
}
"""


@pytest.mark.parametrize("backend_host", ["127.0.0.1", "0.0.0.0", "localhost"])
@pytest.mark.parametrize("enabled", [True, False])
@pytest.mark.asyncio
async def test_command_setting_controls_real_connections_and_protects_backend(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, enabled: bool, backend_host: str
) -> None:
    testbed = bootstrap_runtime_testbed(tmp_path=tmp_path, monkeypatch=monkeypatch)
    ordinary = start_tcp_probe_server()
    protected = start_tcp_probe_server()
    monkeypatch.setenv("PANTARAY_LOCAL_BACKEND_BOUND_HOST", backend_host)
    monkeypatch.setenv("PANTARAY_LOCAL_BACKEND_BOUND_PORT", str(protected.port))
    update_command_network_enabled(
        db_path=testbed.db_path,
        busy_timeout_ms=1_000,
        user_id="user-1",
        command_network_enabled=enabled,
        now="2026-09-11T00:00:00Z",
    )
    try:
        for server in (ordinary, protected):
            compile_workspace_binary(
                workspace_path=testbed.context.workspace_path,
                executable_name="netprobe",
                source_code=CONNECT_SOURCE.replace("__PORT__", str(server.port)),
            )
            outcome = await execute_bash(testbed=testbed, command="netprobe")
            assert outcome.status == (
                "success" if enabled and server is ordinary else "error"
            ), outcome.output
    finally:
        ordinary.close()
        protected.close()
    assert ordinary.hits == ([b"connected"] if enabled else [])
    assert protected.hits == []


@pytest.mark.asyncio
async def test_network_on_does_not_grant_unix_execution_delegation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    testbed = bootstrap_runtime_testbed(tmp_path=tmp_path, monkeypatch=monkeypatch)
    # The nested workspace fixture can exceed macOS's 104-byte AF_UNIX path limit.
    socket_root = Path(tempfile.mkdtemp(prefix="pnt-ipc-", dir="/tmp")).resolve()
    path = socket_root / "delegate.sock"
    marker = socket_root / "allowed.txt"
    folder = _register_folder_mount(
        db_path=testbed.db_path, real_path=socket_root, display_name="IPC probe"
    )
    with sqlite3.connect(testbed.db_path) as connection:
        connection.execute(
            """INSERT INTO workspace_manifest_roots(
                root_id, manifest_id, source_type, source_id, display_name,
                canonical_real_path, real_path, can_read, can_apply_patch,
                can_process_read, can_process_write, created_at
            ) VALUES ('ipc-probe', ?, 'folder', ?, 'IPC probe', ?, ?, 1, 1, 1, 1, '2026-09-11T00:00:00Z')""",
            (
                testbed.context.manifest_id,
                folder.folder_id,
                str(socket_root),
                str(socket_root),
            ),
        )
    source = r"""
#include <stdio.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/un.h>
#include <unistd.h>
int main(void) {
    FILE *marker = fopen("__MARKER__", "w");
    if (marker == NULL) return 88;
    fputs("filesystem allowed", marker);
    fclose(marker);
    int fd = socket(AF_UNIX, SOCK_STREAM, 0);
    struct sockaddr_un address = {0};
    address.sun_family = AF_UNIX;
    strcpy(address.sun_path, "__PATH__");
    int result = connect(fd, (struct sockaddr *)&address, sizeof(address));
    if (result != 0) perror("connect");
    close(fd);
    return result == 0 ? 0 : 1;
}
""".replace("__PATH__", str(path)).replace("__MARKER__", str(marker))
    try:
        with closing(socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)) as server:
            server.bind(str(path))
            server.listen()
            compile_workspace_binary(
                workspace_path=testbed.context.workspace_path,
                executable_name="ipcprobe",
                source_code=source,
            )
            outcome = await execute_bash(testbed=testbed, command="ipcprobe")
            assert outcome.status == "error", outcome.output
            assert marker.read_text() == "filesystem allowed"
            server.settimeout(0.05)
            with pytest.raises(TimeoutError):
                server.accept()
    finally:
        path.unlink(missing_ok=True)
        marker.unlink(missing_ok=True)
        socket_root.rmdir()


@pytest.mark.parametrize("enabled", [True, False])
@pytest.mark.asyncio
async def test_command_setting_controls_udp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, enabled: bool
) -> None:
    testbed = bootstrap_runtime_testbed(tmp_path=tmp_path, monkeypatch=monkeypatch)
    update_command_network_enabled(
        db_path=testbed.db_path,
        busy_timeout_ms=1_000,
        user_id="user-1",
        command_network_enabled=enabled,
        now="2026-09-11T00:00:00Z",
    )
    with closing(socket.socket(socket.AF_INET, socket.SOCK_DGRAM)) as server:
        server.bind(("127.0.0.1", 0))
        server.settimeout(0.05)
        source = CONNECT_SOURCE.replace(
            "__PORT__", str(server.getsockname()[1])
        ).replace("SOCK_STREAM", "SOCK_DGRAM")
        compile_workspace_binary(
            workspace_path=testbed.context.workspace_path,
            executable_name="udp-probe",
            source_code=source,
        )
        outcome = await execute_bash(testbed=testbed, command="udp-probe")
        assert outcome.status == ("success" if enabled else "error"), outcome.output
        if enabled:
            assert server.recv(64) == b"connected"
        else:
            with pytest.raises(TimeoutError):
                server.recv(64)
