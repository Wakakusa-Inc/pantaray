from __future__ import annotations

from pathlib import Path

import pytest

from .support import (
    SEATBELT_SKIP_REASON,
    bootstrap_runtime_testbed,
    compile_workspace_binary,
    execute_bash,
    seatbelt_available,
)

pytestmark = pytest.mark.skipif(not seatbelt_available(), reason=SEATBELT_SKIP_REASON)


def _write_outside_source(target_path: Path) -> str:
    return f"""
#include <fcntl.h>
#include <stdio.h>
#include <unistd.h>

int main(void) {{
    int fd = open("{target_path}", O_CREAT | O_WRONLY | O_TRUNC, 0644);
    if (fd < 0) {{
        perror("open");
        return 111;
    }}
    if (write(fd, "x", 1) != 1) {{
        perror("write");
        close(fd);
        return 112;
    }}
    close(fd);
    return 0;
}}
"""


@pytest.mark.asyncio
async def test_workspace_escape_is_blocked_by_sandbox(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    testbed = bootstrap_runtime_testbed(tmp_path=tmp_path, monkeypatch=monkeypatch)
    outside_path = tmp_path / "outside.txt"
    compile_workspace_binary(
        workspace_path=testbed.context.workspace_path,
        executable_name="escapeprobe",
        source_code=_write_outside_source(outside_path),
    )

    outcome = await execute_bash(testbed=testbed, command="escapeprobe")

    assert outcome.status == "error"
    assert outcome.output["exit_code"] == 111
    assert outcome.output["stderr"] == "open: Operation not permitted\n"
    assert not outside_path.exists()
