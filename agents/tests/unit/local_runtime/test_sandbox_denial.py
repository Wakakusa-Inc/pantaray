from __future__ import annotations

import pytest

from pantaray_agents.local_runtime.tooling.sandbox.sandbox_denial import (
    is_likely_sandbox_denied,
)

CODEX_EXEC_STDERR = (
    "Error: failed to initialize in-process app-server client: "
    "Operation not permitted (os error 1)\n"
)


@pytest.mark.parametrize(
    ("stdout", "stderr"),
    [
        ("", CODEX_EXEC_STDERR),
        ("touch: out.txt: Permission denied\n", ""),
        ("", "OSError: [Errno 30] Read-only file system: '/x'\n"),
    ],
)
def test_a_failure_that_names_a_denial_is_likely_denied(
    stdout: str, stderr: str
) -> None:
    assert is_likely_sandbox_denied(exit_code=1, stdout=stdout, stderr=stderr)


def test_a_success_is_never_denied_whatever_it_printed() -> None:
    assert not is_likely_sandbox_denied(
        exit_code=0, stdout="", stderr=CODEX_EXEC_STDERR
    )


@pytest.mark.parametrize("exit_code", [2, 126, 127])
def test_usage_exec_and_missing_command_exits_are_not_denied_writes(
    exit_code: int,
) -> None:
    assert not is_likely_sandbox_denied(
        exit_code=exit_code, stdout="", stderr="bash: ./run.sh: Permission denied\n"
    )


def test_a_failure_without_denial_words_is_the_command_s_own() -> None:
    assert not is_likely_sandbox_denied(
        exit_code=1, stdout="", stderr="error: unknown option '--frobnicate'\n"
    )
