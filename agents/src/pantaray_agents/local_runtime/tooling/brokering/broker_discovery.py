from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Literal

from pantaray_agents.schema.agent.base import JSONValue
from pantaray_agents.schema.read_access import READ_ACCESS_SCOPE_FULL_ACCESS

from ..action_plan_document import ACTION_PLAN_FILENAME
from ..sandbox.seatbelt_profiles import render_ripgrep_seatbelt_profile
from .broker_common import (
    BrokerContext,
    BrokerPolicyError,
    ensure_session_capabilities,
)
from .broker_discovery_paths import (
    DiscoveryPath,
    DiscoveryTruncationReason,
    entry_for_discovery_path,
    list_discovery_paths,
)
from .broker_discovery_ripgrep import (
    RipgrepGrepMatch,
    run_ripgrep_files,
    run_ripgrep_grep,
)
from .broker_outcome import UnprojectedBrokerToolOutcome
from .broker_protocol import (
    ValidatedGlobRequest,
    ValidatedGrepRequest,
    ValidatedListRequest,
)
from .manifest_paths import (
    ResolvedManifestPath,
)
from .private_app_storage import PrivateAppStorage, private_app_storage
from .tool_path_policy import (
    hidden_read_path_filter,
    resolve_read_tool_path,
)

GREP_MAX_LINE_CHARS = 2_000
GREP_MAX_OUTPUT_BYTES = 50 * 1024
DISCOVERY_MAX_SCANNED_PATHS = 20_000
GREP_LINE_TRUNCATION_SUFFIX = f"... (line truncated to {GREP_MAX_LINE_CHARS} chars)"
TRUNCATION_REASON_PRIORITY: dict[DiscoveryTruncationReason, int] = {
    "line_length": 1,
    "limit": 2,
    "scan_budget": 3,
    "timeout": 4,
    "output_bytes": 5,
}


@dataclass(frozen=True, slots=True)
class PreparedGrepLine:
    line: str
    byte_size: int
    truncated: bool


@dataclass(frozen=True, slots=True)
class GrepAppendResult:
    output_bytes: int
    truncation_reason: DiscoveryTruncationReason | None


def _resolve_directory(
    *,
    context: BrokerContext,
    raw_path: str,
    field_name: str,
) -> ResolvedManifestPath:
    del field_name
    return resolve_read_tool_path(
        context=context,
        raw_path=raw_path,
        must_exist=True,
        must_be_dir=True,
    )


def _reject_unsafe_glob_pattern(pattern: str, *, field_name: str) -> None:
    stripped = pattern.strip()
    if not stripped:
        raise BrokerPolicyError(f"{field_name} must not be empty")
    if stripped.startswith("/") or stripped.startswith("~"):
        raise BrokerPolicyError(f"{field_name} must be relative to base_path")
    if any(part == ".." for part in Path(stripped).parts):
        raise BrokerPolicyError(f"{field_name} must not contain parent directory parts")


def _sort_discovery_paths(paths: Iterable[DiscoveryPath]) -> list[DiscoveryPath]:
    return sorted(paths, key=lambda path: str(path.path))


def run_list_executor(
    *,
    context: BrokerContext,
    request: ValidatedListRequest,
) -> UnprojectedBrokerToolOutcome:
    ensure_session_capabilities(context=context)
    base = _resolve_directory(context=context, raw_path=request.path, field_name="path")
    is_hidden = hidden_read_path_filter(context)
    bounded = list_discovery_paths(
        base=base,
        max_depth=request.max_depth,
        limit=request.limit + 1,
        scan_limit=DISCOVERY_MAX_SCANNED_PATHS,
        include_path=lambda path: not is_hidden(path),
        exclude_subtree=private_app_storage(context).prunes,
    )
    visible_paths = bounded.selected
    truncation_reason = bounded.truncation_reason
    if len(visible_paths) > request.limit:
        truncation_reason = _dominant_truncation_reason(
            truncation_reason,
            "limit",
        )
    entries = [
        entry_for_discovery_path(path) for path in visible_paths[: request.limit]
    ]
    entry_values: list[JSONValue] = [_discovery_entry_json(entry) for entry in entries]
    search_text = "\n".join(str(entry["path"]) for entry in entries)
    return UnprojectedBrokerToolOutcome(
        status="success",
        output={
            "status": "success",
            "entries": entry_values,
            "truncated": truncation_reason is not None,
            "truncation_reason": truncation_reason,
            "retry_hint": _retry_hint(
                tool_id="list",
                reason=truncation_reason,
            ),
            "warning": _warning(reason=truncation_reason),
        },
        search_text=search_text,
        file_paths=tuple(str(entry["path"]) for entry in entries),
        file_reference_paths=(
            tuple(str(entry["path"]) for entry in entries if entry["kind"] == "file")
            if base.root in context.manifest_roots
            else ()
        ),
    )


def run_glob_executor(
    *,
    context: BrokerContext,
    request: ValidatedGlobRequest,
) -> UnprojectedBrokerToolOutcome:
    ensure_session_capabilities(context=context)
    base = _resolve_directory(
        context=context,
        raw_path=request.base_path,
        field_name="base_path",
    )
    _reject_unsafe_glob_pattern(request.pattern, field_name="pattern")
    is_hidden = hidden_read_path_filter(context)
    storage = private_app_storage(context)
    scope = storage.search_scope(base.path)
    backend_result = run_ripgrep_files(
        cwd=base.path,
        sandbox_profile=_ripgrep_sandbox_profile(
            context=context, base=base, storage=storage
        ),
        glob_pattern=request.pattern,
        limit=request.limit,
        follow_symlinks=False,
        excluded_relative_path=_private_plan_relative_to_base(
            context=context,
            base=base,
        ),
        pruned_relative_paths=scope.pruned,
        extra_search_paths=scope.own_roots,
        include_path=lambda path: not is_hidden(path),
    )
    selected = [
        DiscoveryPath(path=_backend_path(base, relative_path), kind="file")
        for relative_path in backend_result.relative_paths
    ]
    matches = [
        entry_for_discovery_path(path) for path in _sort_discovery_paths(selected)
    ]
    match_values: list[JSONValue] = [_discovery_entry_json(match) for match in matches]
    search_text = "\n".join(str(match["path"]) for match in matches)
    return UnprojectedBrokerToolOutcome(
        status="success",
        output={
            "status": "success",
            "matches": match_values,
            "truncated": backend_result.truncated,
            "truncation_reason": backend_result.truncation_reason,
            "retry_hint": _retry_hint(
                tool_id="glob",
                reason=backend_result.truncation_reason,
            ),
            "warning": _warning(reason=backend_result.truncation_reason),
        },
        search_text=search_text,
        file_paths=tuple(str(match["path"]) for match in matches),
        file_reference_paths=(
            tuple(str(match["path"]) for match in matches)
            if base.root in context.manifest_roots
            else ()
        ),
    )


def _ripgrep_sandbox_profile(
    *,
    context: BrokerContext,
    base: ResolvedManifestPath,
    storage: PrivateAppStorage,
) -> str:
    # ripgrep reopens what it walks by name, so only the kernel's check on what
    # it really opens holds; the backend's paths are reported as they come.
    full_access = context.read_access_scope == READ_ACCESS_SCOPE_FULL_ACCESS
    return render_ripgrep_seatbelt_profile(
        read_roots=("/",) if full_access else (str(base.root.canonical_real_path),),
        private_storage_roots=tuple(str(root) for root in storage.storage_roots),
        readable_private_roots=tuple(str(root) for root in storage.readable_roots),
        action_plan_path=str(context.scratch_root_path / ACTION_PLAN_FILENAME),
    )


def _backend_path(base: ResolvedManifestPath, relative_path: str) -> Path:
    return base.path / PurePosixPath(relative_path)


def _private_plan_relative_to_base(
    *,
    context: BrokerContext,
    base: ResolvedManifestPath,
) -> str | None:
    try:
        relative = (context.scratch_root_path / ACTION_PLAN_FILENAME).relative_to(
            base.path
        )
    except ValueError:
        relative = Path(ACTION_PLAN_FILENAME)
        ancestor = context.scratch_root_path
        while True:
            if ancestor.samefile(base.path):
                return relative.as_posix()
            if ancestor.parent == ancestor:
                return None
            relative = Path(ancestor.name) / relative
            ancestor = ancestor.parent
    else:
        return relative.as_posix()


def _discovery_entry_json(entry: dict[str, object]) -> dict[str, JSONValue]:
    return {
        "path": str(entry["path"]),
        "kind": str(entry["kind"]),
        "name": str(entry["name"]),
    }


def _append_grep_match(
    *,
    matches: list[dict[str, JSONValue]],
    output_bytes: int,
    base: ResolvedManifestPath,
    match: RipgrepGrepMatch,
) -> GrepAppendResult:
    path = str(_backend_path(base, match.relative_path))
    prepared_line = _prepare_grep_line(
        path=path,
        line_number=match.line_number,
        line=match.line,
    )
    if output_bytes + prepared_line.byte_size > GREP_MAX_OUTPUT_BYTES:
        return GrepAppendResult(
            output_bytes=output_bytes,
            truncation_reason="output_bytes",
        )
    matches.append(
        {
            "path": path,
            "line_number": match.line_number,
            "line": prepared_line.line,
        }
    )
    return GrepAppendResult(
        output_bytes=output_bytes + prepared_line.byte_size,
        truncation_reason="line_length" if prepared_line.truncated else None,
    )


def _build_grep_outcome(
    *,
    matches: list[dict[str, JSONValue]],
    skipped_files: int,
    truncation_reason: DiscoveryTruncationReason | None,
    include_file_references: bool,
) -> UnprojectedBrokerToolOutcome:
    sorted_matches = sorted(matches, key=_grep_match_sort_key)
    search_text = "\n".join(
        f"{match['path']}:{match['line_number']}:{match['line']}"
        for match in sorted_matches
    )
    match_values: list[JSONValue] = []
    for match in sorted_matches:
        match_values.append(dict(match))
    return UnprojectedBrokerToolOutcome(
        status="success",
        output={
            "status": "success",
            "matches": match_values,
            "truncated": truncation_reason is not None,
            "truncation_reason": truncation_reason,
            "retry_hint": _retry_hint(
                tool_id="grep",
                reason=truncation_reason,
                skipped_files=skipped_files,
            ),
            "warning": _warning(
                reason=truncation_reason,
                skipped_files=skipped_files,
            ),
            "skipped_files": skipped_files,
        },
        search_text=search_text,
        file_paths=tuple(str(match["path"]) for match in sorted_matches),
        file_reference_paths=(
            tuple(str(match["path"]) for match in sorted_matches)
            if include_file_references
            else ()
        ),
    )


def _prepare_grep_line(*, path: str, line_number: int, line: str) -> PreparedGrepLine:
    truncated = len(line) > GREP_MAX_LINE_CHARS
    if truncated:
        line = f"{line[:GREP_MAX_LINE_CHARS]}{GREP_LINE_TRUNCATION_SUFFIX}"
    byte_size = len(f"{path}:{line_number}:{line}\n".encode("utf-8", errors="replace"))
    return PreparedGrepLine(line=line, byte_size=byte_size, truncated=truncated)


def _grep_match_sort_key(match: dict[str, JSONValue]) -> tuple[str, int]:
    line_number = match["line_number"]
    return (
        str(match["path"]),
        line_number
        if isinstance(line_number, int) and not isinstance(line_number, bool)
        else 0,
    )


def run_grep_executor(
    *,
    context: BrokerContext,
    request: ValidatedGrepRequest,
) -> UnprojectedBrokerToolOutcome:
    ensure_session_capabilities(context=context)
    base = _resolve_directory(
        context=context,
        raw_path=request.base_path,
        field_name="base_path",
    )
    if request.include_glob is not None:
        _reject_unsafe_glob_pattern(request.include_glob, field_name="include_glob")
    is_hidden = hidden_read_path_filter(context)
    storage = private_app_storage(context)
    scope = storage.search_scope(base.path)
    backend_result = run_ripgrep_grep(
        cwd=base.path,
        sandbox_profile=_ripgrep_sandbox_profile(
            context=context, base=base, storage=storage
        ),
        pattern=request.pattern,
        include_glob=request.include_glob,
        max_matches=request.max_matches,
        follow_symlinks=False,
        excluded_relative_path=_private_plan_relative_to_base(
            context=context,
            base=base,
        ),
        pruned_relative_paths=scope.pruned,
        extra_search_paths=scope.own_roots,
        include_path=lambda path: not is_hidden(path),
    )
    matches: list[dict[str, JSONValue]] = []
    truncation_reason: DiscoveryTruncationReason | None = (
        backend_result.truncation_reason
    )
    output_bytes = 0
    for backend_match in backend_result.matches:
        append_result = _append_grep_match(
            matches=matches,
            output_bytes=output_bytes,
            base=base,
            match=backend_match,
        )
        output_bytes = append_result.output_bytes
        truncation_reason = _dominant_truncation_reason(
            truncation_reason,
            append_result.truncation_reason,
        )
        if append_result.truncation_reason == "output_bytes":
            break
    return _build_grep_outcome(
        matches=matches,
        skipped_files=backend_result.skipped_files,
        truncation_reason=truncation_reason,
        include_file_references=base.root in context.manifest_roots,
    )


def _dominant_truncation_reason(
    current: DiscoveryTruncationReason | None,
    candidate: DiscoveryTruncationReason | None,
) -> DiscoveryTruncationReason | None:
    if candidate is None:
        return current
    if current is None:
        return candidate
    return (
        candidate
        if TRUNCATION_REASON_PRIORITY[candidate] > TRUNCATION_REASON_PRIORITY[current]
        else current
    )


def _retry_hint(
    *,
    tool_id: Literal["list", "glob", "grep"],
    reason: DiscoveryTruncationReason | None,
    skipped_files: int = 0,
) -> str | None:
    if reason is None and skipped_files <= 0:
        return None
    if tool_id == "list":
        if reason == "limit":
            return "Retry list with a narrower path or smaller max_depth."
        if reason == "scan_budget":
            return "Retry list with a narrower path."
    if tool_id == "glob":
        if reason == "limit":
            return "Retry glob with a narrower base_path or more specific pattern."
        if reason == "timeout":
            return "Retry glob with a narrower base_path."
        if reason == "output_bytes":
            return "Retry glob with a more specific pattern to reduce result volume."
    if tool_id == "grep":
        if reason == "limit":
            return "Retry grep with a narrower base_path, include_glob, or pattern."
        if reason == "timeout":
            return "Retry grep with a narrower base_path or include_glob."
        if reason == "output_bytes":
            return "Retry grep with a narrower base_path, include_glob, or more specific pattern."
        if reason == "line_length":
            return "Retry grep with include_glob or a more specific pattern."
        if skipped_files > 0:
            return "Retry grep with a narrower base_path or include_glob to reduce skipped files."
    return "Retry with a narrower local workspace path or more specific query."


def _warning(
    *,
    reason: DiscoveryTruncationReason | None,
    skipped_files: int = 0,
) -> str | None:
    warnings: list[str] = []
    if reason == "limit":
        warnings.append("Results were truncated because the result limit was reached.")
    elif reason == "scan_budget":
        warnings.append(
            "Results were truncated because the discovery scan budget was reached."
        )
    elif reason == "timeout":
        warnings.append("Results were truncated because the search backend timed out.")
    elif reason == "output_bytes":
        warnings.append(
            "Results were truncated because the output byte limit was reached."
        )
    elif reason == "line_length":
        warnings.append(
            "One or more matching lines were shortened because they exceeded the line length limit."
        )
    if skipped_files > 0:
        warnings.append(
            f"{skipped_files} file(s) were skipped by the search backend, so the result is partial."
        )
    if not warnings:
        return None
    return " ".join(warnings)
