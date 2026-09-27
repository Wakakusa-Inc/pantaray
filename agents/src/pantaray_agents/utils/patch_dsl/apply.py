from __future__ import annotations

from dataclasses import dataclass

from .errors import (
    PatchContextAmbiguousError,
    PatchContextNotFoundError,
    PatchDslPathError,
)
from .models import PatchChunk, PatchFileChange, PatchOperation, PatchSet
from .parser import parse_patch_dsl


@dataclass(frozen=True, slots=True)
class PatchTextApplyResult:
    path: str
    updated_text: str


def apply_patch_dsl_to_text(
    *,
    base_text: str,
    patch_text: str,
    expected_path: str,
) -> PatchTextApplyResult:
    patch = parse_patch_dsl(patch_text)
    if len(patch.changes) != 1:
        raise PatchDslPathError(
            "PATCH_DSL_ARTIFACT_SINGLE_FILE: artifact patch must update exactly one file."
        )
    change = patch.changes[0]
    if change.operation is not PatchOperation.UPDATE:
        raise PatchDslPathError(
            "PATCH_DSL_ARTIFACT_UPDATE_ONLY: artifact patch only supports Update File."
        )
    if change.path != expected_path:
        raise PatchDslPathError(
            f"PATCH_DSL_ARTIFACT_PATH_MISMATCH: expected {expected_path!r}, got {change.path!r}."
        )
    return PatchTextApplyResult(
        path=change.path,
        updated_text=_apply_chunks(base_text, change.chunks),
    )


def derive_file_changes(
    patch: PatchSet,
    documents: dict[str, str],
) -> tuple[PatchFileChange, ...]:
    _validate_no_path_conflicts(patch)
    changes: list[PatchFileChange] = []
    for change in patch.changes:
        if change.operation is PatchOperation.ADD:
            _ensure_missing(documents=documents, path=change.path)
            changes.append(
                PatchFileChange(
                    operation=PatchOperation.ADD,
                    path=change.path,
                    old_text="",
                    new_text=change.contents,
                )
            )
            continue
        if change.operation is PatchOperation.DELETE:
            old_text = _read_existing(documents=documents, path=change.path)
            changes.append(
                PatchFileChange(
                    operation=PatchOperation.DELETE,
                    path=change.path,
                    old_text=old_text,
                    new_text="",
                )
            )
            continue
        if change.operation is PatchOperation.UPDATE:
            old_text = _read_existing(documents=documents, path=change.path)
            changes.append(
                PatchFileChange(
                    operation=PatchOperation.UPDATE,
                    path=change.path,
                    old_text=old_text,
                    new_text=_apply_chunks(old_text, change.chunks),
                )
            )
            continue
        if change.operation is PatchOperation.MOVE:
            if change.move_path is None:
                raise PatchDslPathError(
                    "PATCH_DSL_MOVE_TARGET_MISSING: move target is required."
                )
            old_text = _read_existing(documents=documents, path=change.path)
            _ensure_missing(documents=documents, path=change.move_path)
            changes.append(
                PatchFileChange(
                    operation=PatchOperation.MOVE,
                    path=change.path,
                    old_text=old_text,
                    new_text=_apply_chunks(old_text, change.chunks),
                    move_path=change.move_path,
                )
            )
            continue
    return tuple(changes)


def _validate_no_path_conflicts(patch: PatchSet) -> None:
    seen: dict[str, str] = {}
    for change in patch.changes:
        _record_path_role(seen=seen, path=change.path, role=change.operation.value)
        if change.move_path is not None:
            _record_path_role(seen=seen, path=change.move_path, role="move_target")


def _record_path_role(*, seen: dict[str, str], path: str, role: str) -> None:
    existing = seen.get(path)
    if existing is not None:
        raise PatchDslPathError(
            "PATCH_DSL_PATH_CONFLICT: path appears in multiple patch operations "
            f"({path}: {existing}, {role}). Split dependent edits into separate patches."
        )
    seen[path] = role


def _read_existing(*, documents: dict[str, str], path: str) -> str:
    if path not in documents:
        raise PatchDslPathError(
            f"PATCH_DSL_TARGET_MISSING: target file does not exist: {path}"
        )
    return documents[path]


def _ensure_missing(*, documents: dict[str, str], path: str) -> None:
    if path in documents:
        raise PatchDslPathError(
            f"PATCH_DSL_TARGET_EXISTS: target file already exists: {path}"
        )


def _split_text(text: str) -> tuple[list[str], bool]:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    if normalized == "":
        return [], False
    has_trailing_newline = normalized.endswith("\n")
    if has_trailing_newline:
        normalized = normalized[:-1]
    return normalized.split("\n") if normalized else [], has_trailing_newline


def _join_text(lines: list[str], *, trailing_newline: bool) -> str:
    if not lines:
        return "\n" if trailing_newline else ""
    return "\n".join(lines) + ("\n" if trailing_newline else "")


def _apply_chunks(base_text: str, chunks: tuple[PatchChunk, ...]) -> str:
    current_lines, trailing_newline = _split_text(base_text)
    cursor = 0
    for chunk in chunks:
        old_lines = _old_lines_for_chunk(chunk)
        new_lines = _new_lines_for_chunk(chunk)
        match_index = _find_unique_match(
            current_lines=current_lines,
            old_lines=old_lines,
            cursor=cursor,
        )
        current_lines = (
            current_lines[:match_index]
            + new_lines
            + current_lines[match_index + len(old_lines) :]
        )
        cursor = match_index + len(new_lines)
        if new_lines:
            trailing_newline = True
    return _join_text(current_lines, trailing_newline=trailing_newline)


def _old_lines_for_chunk(chunk: PatchChunk) -> list[str]:
    return [line[1:] for line in chunk.lines if line.startswith((" ", "-"))]


def _new_lines_for_chunk(chunk: PatchChunk) -> list[str]:
    return [line[1:] for line in chunk.lines if line.startswith((" ", "+"))]


def _find_unique_match(
    *,
    current_lines: list[str],
    old_lines: list[str],
    cursor: int,
) -> int:
    if not old_lines:
        if current_lines:
            raise PatchContextAmbiguousError(
                "PATCH_CONTEXT_AMBIGUOUS: insertion-only chunk requires context unless the file is empty."
            )
        return 0

    matches: list[int] = []
    last_start = len(current_lines) - len(old_lines)
    for index in range(cursor, last_start + 1):
        if current_lines[index : index + len(old_lines)] == old_lines:
            matches.append(index)
            if len(matches) > 1:
                raise PatchContextAmbiguousError(
                    "PATCH_CONTEXT_AMBIGUOUS: patch chunk matched multiple locations; add more context."
                )
    if not matches:
        raise PatchContextNotFoundError(
            "PATCH_CONTEXT_NOT_FOUND: patch chunk did not match the current file content."
        )
    return matches[0]
