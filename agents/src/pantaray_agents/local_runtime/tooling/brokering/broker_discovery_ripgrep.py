from __future__ import annotations

import json
import shutil
import subprocess
import sys
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import IO, Literal, cast

from pantaray_agents.schema.agent.base import JSONValue

from .broker_common import BrokerPolicyError

RIPGREP_COMMAND = "rg"
SANDBOX_EXEC = "/usr/bin/sandbox-exec"
# Discovery runs outside the command sandbox; never select a workspace executable.
RIPGREP_TRUSTED_PATH = "/opt/homebrew/bin:/usr/local/bin:/usr/bin"
RIPGREP_TIMEOUT_SECONDS = 5.0
RIPGREP_MAX_STDOUT_BYTES = 2 * 1024 * 1024
RIPGREP_MAX_STDERR_CHARS = 8_192
RIPGREP_MAX_FILE_SIZE = "1M"
RIPGREP_REGEX_ERROR_MARKERS = (
    "regex parse error",
    "error parsing regex",
)
RIPGREP_GLOB_ERROR_MARKERS = (
    "glob parse error",
    "error parsing glob",
)
RIPGREP_COMMON_ARGS = (
    # A config file named by the inherited RIPGREP_CONFIG_PATH would change what
    # a search returns, and its --pre would run a program nobody approved.
    "--no-config",
    "--hidden",
    "--no-ignore",
    "--color",
    "never",
)
GLOB_PATTERN_FIX_HINT = (
    "Use a base_path-relative ripgrep glob such as **/*.py. Do not pass malformed "
    "character classes, absolute paths, or parent directory parts."
)
GLOB_PATTERN_EXAMPLES = ('{"base_path":".","pattern":"**/*.py","limit":100}',)
GREP_PATTERN_FIX_HINT = (
    "grep.pattern is a ripgrep regular expression. Escape regex metacharacters for "
    "literal text, for example use \\( for a literal opening parenthesis."
)
GREP_PATTERN_EXAMPLES = (
    '{"base_path":".","pattern":"TODO","include_glob":"**/*.py","max_matches":100}',
    '{"base_path":".","pattern":"\\\\(","include_glob":"**/*.txt","max_matches":100}',
)
GREP_INCLUDE_GLOB_FIX_HINT = (
    "grep.include_glob is a base_path-relative ripgrep glob such as **/*.py. "
    "Do not pass malformed character classes, absolute paths, or parent directory parts."
)
GREP_INCLUDE_GLOB_EXAMPLES = (
    '{"base_path":".","pattern":"TODO","include_glob":"**/*.py","max_matches":100}',
)


@dataclass(frozen=True, slots=True)
class RipgrepRunResult:
    exit_code: int | None
    stderr: str
    stderr_truncated: bool
    timed_out: bool
    stdout_truncated: bool
    stopped_early: bool


@dataclass(frozen=True, slots=True)
class RipgrepGlobResult:
    relative_paths: tuple[str, ...]
    truncated: bool
    truncation_reason: RipgrepTruncationReason | None
    timed_out: bool


@dataclass(frozen=True, slots=True)
class RipgrepGrepMatch:
    relative_path: str
    line_number: int
    line: str


@dataclass(frozen=True, slots=True)
class RipgrepGrepResult:
    matches: tuple[RipgrepGrepMatch, ...]
    truncated: bool
    truncation_reason: RipgrepTruncationReason | None
    timed_out: bool
    skipped_files: int


@dataclass(frozen=True, slots=True)
class StderrDrainResult:
    stderr: str
    truncated: bool


LineHandler = Callable[[str], bool]
RipgrepTruncationReason = Literal["limit", "timeout", "output_bytes"]


def run_ripgrep_files(
    *,
    cwd: Path,
    sandbox_profile: str,
    glob_pattern: str,
    limit: int,
    follow_symlinks: bool = False,
    excluded_relative_path: str | None = None,
    pruned_relative_paths: tuple[str, ...] = (),
    extra_search_paths: tuple[str, ...] = (),
    include_path: Callable[[Path], bool] | None = None,
) -> RipgrepGlobResult:
    matches: list[str] = []
    truncated = False

    def handle_line(line: str) -> bool:
        nonlocal truncated
        if not line:
            return True
        if _is_excluded_relative_path(line, excluded_relative_path):
            return True
        if include_path is not None and not include_path(cwd / PurePosixPath(line)):
            return True
        if len(matches) >= limit:
            truncated = True
            return False
        matches.append(line)
        return True

    result = _run_ripgrep_lines(
        argv=(
            str(_resolve_ripgrep_executable()),
            "--files",
            *RIPGREP_COMMON_ARGS,
            *(("--follow",) if follow_symlinks else ()),
            "--glob",
            glob_pattern,
            *(
                ("--glob", _literal_exclusion_glob(excluded_relative_path))
                if excluded_relative_path
                else ()
            ),
            *_pruning_args(pruned_relative_paths),
            "--",
            ".",
            *extra_search_paths,
        ),
        cwd=cwd,
        sandbox_profile=sandbox_profile,
        handle_line=handle_line,
    )
    _raise_if_ripgrep_glob_failed(result=result)
    return RipgrepGlobResult(
        relative_paths=tuple(matches),
        truncated=truncated or result.stdout_truncated or result.timed_out,
        truncation_reason=_ripgrep_truncation_reason(
            limit_reached=truncated,
            result=result,
        ),
        timed_out=result.timed_out,
    )


def run_ripgrep_grep(
    *,
    cwd: Path,
    sandbox_profile: str,
    pattern: str,
    include_glob: str | None,
    max_matches: int,
    follow_symlinks: bool = False,
    excluded_relative_path: str | None = None,
    pruned_relative_paths: tuple[str, ...] = (),
    extra_search_paths: tuple[str, ...] = (),
    include_path: Callable[[Path], bool] | None = None,
) -> RipgrepGrepResult:
    matches: list[RipgrepGrepMatch] = []
    truncated = False
    skipped_files = 0

    def handle_line(line: str) -> bool:
        nonlocal skipped_files, truncated
        event = _parse_json_line(line)
        if event is None:
            return True
        event_type = event.get("type")
        data = event.get("data")
        if not isinstance(event_type, str) or not isinstance(data, dict):
            return True
        if event_type == "match":
            match = _parse_match_event(data)
            if match is None:
                return True
            if _is_excluded_relative_path(
                match.relative_path,
                excluded_relative_path,
            ):
                return True
            if include_path is not None and not include_path(
                cwd / PurePosixPath(match.relative_path)
            ):
                return True
            if len(matches) >= max_matches:
                truncated = True
                return False
            matches.append(match)
        elif event_type == "summary":
            stats = data.get("stats")
            if isinstance(stats, dict):
                searches_with_errors = stats.get("searches_with_errors")
                if isinstance(searches_with_errors, int):
                    skipped_files = max(skipped_files, searches_with_errors)
        return True

    argv = [
        str(_resolve_ripgrep_executable()),
        "--json",
        *RIPGREP_COMMON_ARGS,
        "--line-number",
        "--with-filename",
        "--max-filesize",
        RIPGREP_MAX_FILE_SIZE,
    ]
    if follow_symlinks:
        argv.append("--follow")
    if include_glob is not None:
        argv.extend(("--glob", include_glob))
    if excluded_relative_path is not None:
        argv.extend(("--glob", _literal_exclusion_glob(excluded_relative_path)))
    argv.extend(_pruning_args(pruned_relative_paths))
    argv.extend(("--", pattern, ".", *extra_search_paths))
    result = _run_ripgrep_lines(
        argv=tuple(argv),
        cwd=cwd,
        sandbox_profile=sandbox_profile,
        handle_line=handle_line,
    )
    _raise_if_ripgrep_grep_failed(result=result)
    return RipgrepGrepResult(
        matches=tuple(matches),
        truncated=truncated or result.stdout_truncated or result.timed_out,
        truncation_reason=_ripgrep_truncation_reason(
            limit_reached=truncated,
            result=result,
        ),
        timed_out=result.timed_out,
        skipped_files=skipped_files,
    )


def _is_excluded_relative_path(path: str, excluded: str | None) -> bool:
    if excluded is None:
        return False
    candidate = PurePosixPath(path)
    private = PurePosixPath(excluded)
    return (
        candidate.parent == private.parent
        and candidate.name.casefold() == private.name.casefold()
    )


def _pruning_args(relative_paths: tuple[str, ...]) -> tuple[str, ...]:
    # An excluded directory is not descended, so nothing under it is read or
    # charged to the output budget; an explicit search path still is.
    return tuple(
        argument
        for relative_path in relative_paths
        for argument in ("--glob", _literal_exclusion_glob(relative_path))
    )


def _literal_exclusion_glob(relative_path: str) -> str:
    # Every component matches case-insensitively, like the APFS volume it names.
    escaped = "/".join(
        "".join(
            f"[{character.lower()}{character.upper()}]"
            if character.isascii() and character.isalpha()
            else f"\\{character}"
            if character in r"\*?[]{}"
            else character
            for character in component
        )
        for component in PurePosixPath(relative_path).parts
    )
    return f"!/{escaped}"


def _resolve_ripgrep_executable() -> Path:
    resolved = shutil.which(RIPGREP_COMMAND, path=RIPGREP_TRUSTED_PATH)
    if resolved is None:
        raise BrokerPolicyError(
            "ripgrep backend is unavailable",
            code="DISCOVERY_BACKEND_UNAVAILABLE",
            fix_hint="Install ripgrep in a trusted system location before using glob or grep.",
        )
    return Path(resolved).resolve()


def _run_ripgrep_lines(
    *,
    argv: tuple[str, ...],
    cwd: Path,
    sandbox_profile: str,
    handle_line: LineHandler,
) -> RipgrepRunResult:
    process = subprocess.Popen(
        _sandboxed_argv(argv, sandbox_profile),
        cwd=cwd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    timed_out = False
    stdout_truncated = False
    stopped_early = False
    if process.stdout is None:
        raise BrokerPolicyError(
            "ripgrep backend did not expose stdout",
            code="DISCOVERY_BACKEND_FAILED",
        )
    if process.stderr is None:
        raise BrokerPolicyError(
            "ripgrep backend did not expose stderr",
            code="DISCOVERY_BACKEND_FAILED",
        )
    stderr_drain = _StderrDrain(process.stderr)
    stderr_thread = threading.Thread(target=stderr_drain.run, daemon=True)
    stderr_thread.start()

    def kill_on_timeout() -> None:
        nonlocal timed_out
        timed_out = True
        process.kill()

    timer = threading.Timer(RIPGREP_TIMEOUT_SECONDS, kill_on_timeout)
    timer.start()
    stdout_bytes = 0
    try:
        for raw_line in process.stdout:
            stdout_bytes += len(raw_line.encode("utf-8", errors="replace"))
            if stdout_bytes > RIPGREP_MAX_STDOUT_BYTES:
                stdout_truncated = True
                stopped_early = True
                process.kill()
                break
            if not handle_line(raw_line.rstrip("\n")):
                stopped_early = True
                process.kill()
                break
        exit_code = process.wait()
    finally:
        timer.cancel()
    stderr_thread.join()
    drained_stderr = stderr_drain.result()
    return RipgrepRunResult(
        exit_code=exit_code,
        stderr=drained_stderr.stderr,
        stderr_truncated=drained_stderr.truncated,
        timed_out=timed_out,
        stdout_truncated=stdout_truncated,
        stopped_early=stopped_early,
    )


def _sandboxed_argv(argv: tuple[str, ...], sandbox_profile: str) -> tuple[str, ...]:
    """``argv`` under the seatbelt profile that bounds what ripgrep may read.

    Only macOS has sandbox-exec, and it is the only platform the app ships on.
    The unit tests also run on Linux, where this returns the command unchanged.
    """

    # Keep both paths type-checked on Linux CI; mypy folds a direct sys.platform guard.
    on_macos = sys.platform == "darwin"
    if not on_macos:
        return argv
    return (SANDBOX_EXEC, "-p", sandbox_profile, *argv)


def _parse_json_line(line: str) -> dict[str, JSONValue] | None:
    try:
        payload = json.loads(line)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    return cast(dict[str, JSONValue], payload)


def _parse_match_event(data: dict[str, JSONValue]) -> RipgrepGrepMatch | None:
    path_payload = data.get("path")
    lines_payload = data.get("lines")
    line_number = data.get("line_number")
    if (
        not isinstance(path_payload, dict)
        or not isinstance(lines_payload, dict)
        or not isinstance(line_number, int)
        or isinstance(line_number, bool)
    ):
        return None
    path_text = path_payload.get("text")
    line_text = lines_payload.get("text")
    if not isinstance(path_text, str) or not isinstance(line_text, str):
        return None
    return RipgrepGrepMatch(
        relative_path=path_text,
        line_number=line_number,
        line=line_text.rstrip("\n"),
    )


class _StderrDrain:
    def __init__(self, stream: IO[str]) -> None:
        self._stream = stream
        self._chunks: list[str] = []
        self._stored_chars = 0
        self._truncated = False

    def run(self) -> None:
        while True:
            chunk = self._stream.read(4096)
            if not chunk:
                return
            remaining = RIPGREP_MAX_STDERR_CHARS - self._stored_chars
            if remaining <= 0:
                self._truncated = True
                continue
            self._chunks.append(chunk[:remaining])
            self._stored_chars += min(len(chunk), remaining)
            if len(chunk) > remaining:
                self._truncated = True

    def result(self) -> StderrDrainResult:
        return StderrDrainResult(
            stderr="".join(self._chunks),
            truncated=self._truncated,
        )


def _raise_if_ripgrep_glob_failed(*, result: RipgrepRunResult) -> None:
    if result.exit_code in (0, 1) or result.stopped_early or result.timed_out:
        return
    stderr = result.stderr.lower()
    if _contains_any(stderr, RIPGREP_GLOB_ERROR_MARKERS):
        raise BrokerPolicyError(
            "glob.pattern must be a valid ripgrep glob pattern",
            code="GLOB_PATTERN_INVALID",
            fix_hint=GLOB_PATTERN_FIX_HINT,
            examples=GLOB_PATTERN_EXAMPLES,
        )
    raise BrokerPolicyError(
        "ripgrep discovery backend failed",
        code="GLOB_BACKEND_FAILED",
        fix_hint=_stderr_hint(result.stderr),
    )


def _raise_if_ripgrep_grep_failed(*, result: RipgrepRunResult) -> None:
    if result.exit_code in (0, 1) or result.stopped_early or result.timed_out:
        return
    stderr = result.stderr.lower()
    if _contains_any(stderr, RIPGREP_REGEX_ERROR_MARKERS):
        raise BrokerPolicyError(
            "grep.pattern must be a valid ripgrep regular expression",
            code="GREP_PATTERN_INVALID",
            fix_hint=GREP_PATTERN_FIX_HINT,
            examples=GREP_PATTERN_EXAMPLES,
        )
    if _contains_any(stderr, RIPGREP_GLOB_ERROR_MARKERS):
        raise BrokerPolicyError(
            "grep.include_glob must be a valid ripgrep glob pattern",
            code="GREP_INCLUDE_GLOB_INVALID",
            fix_hint=GREP_INCLUDE_GLOB_FIX_HINT,
            examples=GREP_INCLUDE_GLOB_EXAMPLES,
        )
    raise BrokerPolicyError(
        "ripgrep grep backend failed",
        code="GREP_BACKEND_FAILED",
        fix_hint=_stderr_hint(result.stderr),
    )


def _contains_any(text: str, markers: tuple[str, ...]) -> bool:
    return any(marker in text for marker in markers)


def _ripgrep_truncation_reason(
    *,
    limit_reached: bool,
    result: RipgrepRunResult,
) -> RipgrepTruncationReason | None:
    if result.stdout_truncated:
        return "output_bytes"
    if result.timed_out:
        return "timeout"
    if limit_reached:
        return "limit"
    return None


def _stderr_hint(stderr: str) -> str | None:
    stripped = stderr.strip()
    if not stripped:
        return None
    return stripped[:RIPGREP_MAX_STDERR_CHARS]
