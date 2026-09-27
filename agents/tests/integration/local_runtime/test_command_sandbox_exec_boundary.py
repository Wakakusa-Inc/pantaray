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


EXEC_EXTERNAL_SOURCE = r"""
#include <stdio.h>
#include <unistd.h>

int main(void) {
    char *const argv[] = {"/bin/pwd", NULL};
    execv("/bin/pwd", argv);
    perror("execv");
    return 111;
}
"""


@pytest.mark.asyncio
async def test_workspace_exec_boundary_allows_sandboxed_child(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    testbed = bootstrap_runtime_testbed(tmp_path=tmp_path, monkeypatch=monkeypatch)
    compile_workspace_binary(
        workspace_path=testbed.context.workspace_path,
        executable_name="execprobe",
        source_code=EXEC_EXTERNAL_SOURCE,
    )

    outcome = await execute_bash(testbed=testbed, command="execprobe")

    assert outcome.status == "success", outcome.output
    assert outcome.output["stdout"].strip() == str(testbed.context.workspace_path)
