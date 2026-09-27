from __future__ import annotations

from pathlib import Path

import pytest

from .support import (
    SEATBELT_SKIP_REASON,
    bootstrap_runtime_testbed,
    execute_bash,
    seatbelt_available,
)

pytestmark = pytest.mark.skipif(not seatbelt_available(), reason=SEATBELT_SKIP_REASON)


@pytest.mark.asyncio
async def test_shell_syntax_and_repo_script_create_expected_artifacts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    testbed = bootstrap_runtime_testbed(tmp_path=tmp_path, monkeypatch=monkeypatch)
    workspace = testbed.context.workspace_path
    (workspace / "subdir").mkdir()
    (workspace / "subdir/process.sh").write_text(
        '#!/bin/bash\n[ "$INPUT_NAME" = "numbers.txt" ] || exit 9\n'
        'sort -n "$INPUT_NAME" | uniq > sorted.txt\n'
    )
    (workspace / "subdir/process.sh").chmod(0o755)
    outcome = await execute_bash(
        testbed=testbed,
        command="""cd subdir
cat > numbers.txt <<'DATA'
3
1
3
2
DATA
INPUT_NAME=numbers.txt ./process.sh && cat sorted.txt
printf '%s\n' "$(wc -l < sorted.txt)" > count.txt
""",
    )
    assert outcome.status == "success", outcome.output
    assert outcome.output["stdout"] == "1\n2\n3\n"
    assert (workspace / "subdir/sorted.txt").read_text() == "1\n2\n3\n"
    assert int((workspace / "subdir/count.txt").read_text().strip()) == 3


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("command", "exit_code", "error_text"),
    [
        ("if then", 2, "syntax error"),
        ("pantaray_nonexistent_command", 127, "command not found"),
        ("printf partial > partial.txt; exit 7", 7, ""),
        (
            "printf '%s\\n' 'sandbox fixture: execution assertion failed' >&2; exit 4",
            4,
            "sandbox fixture: execution assertion failed\n",
        ),
        (
            "printf '%s\\n' 'Operation not permitted: cannot write cache' >&2; exit 111",
            111,
            "Operation not permitted: cannot write cache\n",
        ),
    ],
)
async def test_shell_failure_preserves_exit_and_partial_side_effects(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    command: str,
    exit_code: int,
    error_text: str,
) -> None:
    testbed = bootstrap_runtime_testbed(tmp_path=tmp_path, monkeypatch=monkeypatch)
    outcome = await execute_bash(testbed=testbed, command=command)
    assert outcome.status == "error", outcome.output
    assert outcome.output["exit_code"] == exit_code
    assert error_text in outcome.output["stderr"]
    if exit_code == 7:
        assert (testbed.context.workspace_path / "partial.txt").read_text() == "partial"


@pytest.mark.asyncio
async def test_shell_process_substitution_reads_inherited_pipe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    testbed = bootstrap_runtime_testbed(tmp_path=tmp_path, monkeypatch=monkeypatch)
    outcome = await execute_bash(testbed=testbed, command="cat <(printf pipe-content)")
    assert outcome.status == "success", outcome.output
    assert outcome.output["stdout"] == "pipe-content"
