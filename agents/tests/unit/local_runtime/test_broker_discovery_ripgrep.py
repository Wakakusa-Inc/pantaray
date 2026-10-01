from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from pantaray_agents.local_runtime.tooling.brokering import broker_discovery_ripgrep
from pantaray_agents.local_runtime.tooling.brokering.broker_common import (
    BrokerPolicyError,
)


def test_ripgrep_files_uses_fixed_argv(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}
    monkeypatch.setattr(
        broker_discovery_ripgrep,
        "_resolve_ripgrep_executable",
        lambda: Path("/trusted/bin/rg"),
    )

    def fake_run(
        *,
        argv: tuple[str, ...],
        cwd: Path,
        sandbox_profile: str,
        handle_line: broker_discovery_ripgrep.LineHandler,
    ) -> broker_discovery_ripgrep.RipgrepRunResult:
        captured["argv"] = argv
        captured["cwd"] = cwd
        assert handle_line("src/action[1]/PLAN.MD") is True
        assert handle_line("src/app.py") is True
        assert handle_line("src/other.py") is False
        return broker_discovery_ripgrep.RipgrepRunResult(
            exit_code=0,
            stderr="",
            stderr_truncated=False,
            timed_out=False,
            stdout_truncated=False,
            stopped_early=True,
        )

    monkeypatch.setattr(broker_discovery_ripgrep, "_run_ripgrep_lines", fake_run)

    result = broker_discovery_ripgrep.run_ripgrep_files(
        cwd=tmp_path,
        sandbox_profile="",
        glob_pattern="src/*.py",
        limit=1,
        excluded_relative_path="src/action[1]/plan.md",
    )

    assert captured["cwd"] == tmp_path
    assert captured["argv"] == (
        "/trusted/bin/rg",
        "--files",
        "--hidden",
        "--no-ignore",
        "--color",
        "never",
        "--glob",
        "src/*.py",
        "--glob",
        r"!/[sS][rR][cC]/[aA][cC][tT][iI][oO][nN]\[1\]/[pP][lL][aA][nN].[mM][dD]",
        "--",
        ".",
    )
    assert result.relative_paths == ("src/app.py",)
    assert result.truncated is True


def test_ripgrep_grep_uses_fixed_argv(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}
    monkeypatch.setattr(
        broker_discovery_ripgrep,
        "_resolve_ripgrep_executable",
        lambda: Path("/trusted/bin/rg"),
    )

    def fake_run(
        *,
        argv: tuple[str, ...],
        cwd: Path,
        sandbox_profile: str,
        handle_line: broker_discovery_ripgrep.LineHandler,
    ) -> broker_discovery_ripgrep.RipgrepRunResult:
        captured["argv"] = argv
        captured["cwd"] = cwd
        assert handle_line(
            json.dumps(
                {
                    "type": "match",
                    "data": {
                        "path": {"text": "src/action[1]/PLAN.MD"},
                        "line_number": 1,
                        "lines": {"text": "private needle\n"},
                    },
                }
            )
        )
        assert handle_line(
            json.dumps(
                {
                    "type": "match",
                    "data": {
                        "path": {"text": "src/app.py"},
                        "line_number": 3,
                        "lines": {"text": "needle\n"},
                    },
                }
            )
        )
        return broker_discovery_ripgrep.RipgrepRunResult(
            exit_code=0,
            stderr="",
            stderr_truncated=False,
            timed_out=False,
            stdout_truncated=False,
            stopped_early=False,
        )

    monkeypatch.setattr(broker_discovery_ripgrep, "_run_ripgrep_lines", fake_run)

    result = broker_discovery_ripgrep.run_ripgrep_grep(
        cwd=tmp_path,
        sandbox_profile="",
        pattern="needle",
        include_glob="**/*.py",
        max_matches=10,
        excluded_relative_path="src/action[1]/plan.md",
    )

    assert captured["cwd"] == tmp_path
    assert captured["argv"] == (
        "/trusted/bin/rg",
        "--json",
        "--hidden",
        "--no-ignore",
        "--color",
        "never",
        "--line-number",
        "--with-filename",
        "--max-filesize",
        "1M",
        "--glob",
        "**/*.py",
        "--glob",
        r"!/[sS][rR][cC]/[aA][cC][tT][iI][oO][nN]\[1\]/[pP][lL][aA][nN].[mM][dD]",
        "--",
        "needle",
        ".",
    )
    assert result.matches == (
        broker_discovery_ripgrep.RipgrepGrepMatch(
            relative_path="src/app.py",
            line_number=3,
            line="needle",
        ),
    )


def test_ripgrep_grep_timeout_truncates_without_pattern_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        broker_discovery_ripgrep,
        "_resolve_ripgrep_executable",
        lambda: Path("/trusted/bin/rg"),
    )

    def fake_run(
        *,
        argv: tuple[str, ...],
        cwd: Path,
        sandbox_profile: str,
        handle_line: broker_discovery_ripgrep.LineHandler,
    ) -> broker_discovery_ripgrep.RipgrepRunResult:
        return broker_discovery_ripgrep.RipgrepRunResult(
            exit_code=-9,
            stderr="",
            stderr_truncated=False,
            timed_out=True,
            stdout_truncated=False,
            stopped_early=False,
        )

    monkeypatch.setattr(broker_discovery_ripgrep, "_run_ripgrep_lines", fake_run)

    result = broker_discovery_ripgrep.run_ripgrep_grep(
        cwd=tmp_path,
        sandbox_profile="",
        pattern="needle",
        include_glob=None,
        max_matches=10,
    )

    assert result.truncated is True
    assert result.timed_out is True


def test_ripgrep_files_classifies_glob_parse_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        broker_discovery_ripgrep,
        "_resolve_ripgrep_executable",
        lambda: Path("/trusted/bin/rg"),
    )

    def fake_run(
        *,
        argv: tuple[str, ...],
        cwd: Path,
        sandbox_profile: str,
        handle_line: broker_discovery_ripgrep.LineHandler,
    ) -> broker_discovery_ripgrep.RipgrepRunResult:
        return broker_discovery_ripgrep.RipgrepRunResult(
            exit_code=2,
            stderr="rg: error parsing glob '[': unclosed character class",
            stderr_truncated=False,
            timed_out=False,
            stdout_truncated=False,
            stopped_early=False,
        )

    monkeypatch.setattr(broker_discovery_ripgrep, "_run_ripgrep_lines", fake_run)

    with pytest.raises(BrokerPolicyError) as exc_info:
        broker_discovery_ripgrep.run_ripgrep_files(
            cwd=tmp_path,
            sandbox_profile="",
            glob_pattern="[",
            limit=10,
        )

    assert exc_info.value.code == "GLOB_PATTERN_INVALID"
    assert exc_info.value.fix_hint == broker_discovery_ripgrep.GLOB_PATTERN_FIX_HINT
    assert exc_info.value.examples == broker_discovery_ripgrep.GLOB_PATTERN_EXAMPLES


def test_ripgrep_runner_drains_stderr_without_timeout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(broker_discovery_ripgrep, "RIPGREP_TIMEOUT_SECONDS", 0.5)
    script = (
        "import sys\n"
        "sys.stderr.write('x' * 200000)\n"
        "sys.stderr.flush()\n"
        "raise SystemExit(2)\n"
    )

    result = broker_discovery_ripgrep._run_ripgrep_lines(
        argv=(sys.executable, "-c", script),
        cwd=tmp_path,
        sandbox_profile="(version 1)\n(allow default)",
        handle_line=lambda line: True,
    )

    assert result.exit_code == 2
    assert result.timed_out is False
    assert result.stderr_truncated is True
    assert len(result.stderr) <= broker_discovery_ripgrep.RIPGREP_MAX_STDERR_CHARS


@pytest.mark.parametrize(
    ("stderr", "expected_code"),
    [
        ("regex parse error:\n    (\nerror: unclosed group", "GREP_PATTERN_INVALID"),
        (
            "glob parse error:\n    [\nerror: unclosed character class",
            "GREP_INCLUDE_GLOB_INVALID",
        ),
        ("rg: ./secret: Permission denied", "GREP_BACKEND_FAILED"),
    ],
)
def test_ripgrep_grep_classifies_backend_failures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    stderr: str,
    expected_code: str,
) -> None:
    monkeypatch.setattr(
        broker_discovery_ripgrep,
        "_resolve_ripgrep_executable",
        lambda: Path("/trusted/bin/rg"),
    )

    def fake_run(
        *,
        argv: tuple[str, ...],
        cwd: Path,
        sandbox_profile: str,
        handle_line: broker_discovery_ripgrep.LineHandler,
    ) -> broker_discovery_ripgrep.RipgrepRunResult:
        return broker_discovery_ripgrep.RipgrepRunResult(
            exit_code=2,
            stderr=stderr,
            stderr_truncated=False,
            timed_out=False,
            stdout_truncated=False,
            stopped_early=False,
        )

    monkeypatch.setattr(broker_discovery_ripgrep, "_run_ripgrep_lines", fake_run)

    with pytest.raises(BrokerPolicyError) as exc_info:
        broker_discovery_ripgrep.run_ripgrep_grep(
            cwd=tmp_path,
            sandbox_profile="",
            pattern="needle",
            include_glob="**/*.py",
            max_matches=10,
        )

    assert exc_info.value.code == expected_code
    if expected_code == "GREP_PATTERN_INVALID":
        assert exc_info.value.fix_hint == broker_discovery_ripgrep.GREP_PATTERN_FIX_HINT
        assert exc_info.value.examples == broker_discovery_ripgrep.GREP_PATTERN_EXAMPLES
    elif expected_code == "GREP_INCLUDE_GLOB_INVALID":
        assert (
            exc_info.value.fix_hint
            == broker_discovery_ripgrep.GREP_INCLUDE_GLOB_FIX_HINT
        )
        assert (
            exc_info.value.examples
            == broker_discovery_ripgrep.GREP_INCLUDE_GLOB_EXAMPLES
        )


@pytest.mark.parametrize("installed", [True, False])
def test_ripgrep_selection_never_uses_parent_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, installed: bool
) -> None:
    trusted = tmp_path / "trusted"
    untrusted = tmp_path / "workspace"
    for directory in (trusted, untrusted):
        directory.mkdir()
    for directory in (trusted, untrusted) if installed else (untrusted,):
        executable = directory / "rg"
        executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        executable.chmod(0o755)
    monkeypatch.setenv("PATH", str(untrusted))
    monkeypatch.setattr(broker_discovery_ripgrep, "RIPGREP_TRUSTED_PATH", str(trusted))
    if installed:
        assert broker_discovery_ripgrep._resolve_ripgrep_executable() == trusted / "rg"
    else:
        with pytest.raises(BrokerPolicyError) as exc_info:
            broker_discovery_ripgrep._resolve_ripgrep_executable()
        assert exc_info.value.code == "DISCOVERY_BACKEND_UNAVAILABLE"
