"""Structured artifact patch application for LLM-authored document edits."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from pantaray_agents.schema.agent.base import JSONValue
from pantaray_agents.utils.artifact_text_patch import ArtifactTextPatchError

OLD_LINE_PREVIEW_LIMIT = 5
MAX_CONTEXT_GAP_LINES = 80
MAX_CHUNK_SPAN_LINES = 160
MAX_START_CANDIDATES = 10
LINE_OMISSION_MARKER = "<OMITTED>"


class StructuredPatchLineOp(StrEnum):
    CONTEXT = "context"
    REMOVE = "remove"
    ADD = "add"


@dataclass(frozen=True, slots=True)
class StructuredPatchLine:
    op: StructuredPatchLineOp
    text: str
    line_index: int


@dataclass(frozen=True, slots=True)
class StructuredPatchChunk:
    lines: tuple[StructuredPatchLine, ...]


@dataclass(frozen=True, slots=True)
class StructuredArtifactPatch:
    chunks: tuple[StructuredPatchChunk, ...]


@dataclass(frozen=True, slots=True)
class _OrderedChunkMatch:
    positions_by_line_index: dict[int, int]
    start: int
    end: int


class StructuredArtifactPatchError(ArtifactTextPatchError):
    """Structured artifact patch failed validation or application."""

    def __init__(
        self,
        message: str,
        *,
        details: dict[str, JSONValue] | None = None,
    ) -> None:
        super().__init__(message)
        self.details = details or {}


def parse_structured_artifact_patch_request(
    tool_input: object,
) -> StructuredArtifactPatch:
    if not isinstance(tool_input, dict):
        raise RuntimeError("validated artifact_patch request must be an object")
    chunks_value = tool_input.get("chunks")
    if not isinstance(chunks_value, list):
        raise RuntimeError("validated artifact_patch request must include chunks")
    if not chunks_value:
        raise StructuredArtifactPatchError(
            "PATCH_STRUCTURED_EMPTY: chunks must include at least one edit chunk."
        )
    return StructuredArtifactPatch(
        chunks=tuple(
            _parse_chunk(chunk_value, chunk_index)
            for chunk_index, chunk_value in enumerate(chunks_value)
        )
    )


def apply_structured_artifact_patch(
    *,
    base_text: str,
    patch: StructuredArtifactPatch,
) -> str:
    current_lines, trailing_newline = _split_text(base_text)
    cursor = 0
    for chunk_index, chunk in enumerate(patch.chunks):
        old_entries = _old_entries_for_chunk(chunk)
        match = _find_unique_ordered_span(
            current_lines=current_lines,
            old_entries=old_entries,
            cursor=cursor,
            chunk_index=chunk_index,
        )
        current_lines, cursor = _apply_chunk_at_match(
            current_lines=current_lines,
            chunk=chunk,
            match=match,
        )
        if any(line.op == StructuredPatchLineOp.ADD for line in chunk.lines):
            trailing_newline = True
    return _join_text(current_lines, trailing_newline=trailing_newline)


def _parse_chunk(value: object, chunk_index: int) -> StructuredPatchChunk:
    if not isinstance(value, dict):
        raise RuntimeError("validated artifact_patch chunk must be an object")
    lines_value = value.get("lines")
    if not isinstance(lines_value, list):
        raise RuntimeError("validated artifact_patch chunk must include lines")
    if not lines_value:
        raise StructuredArtifactPatchError(
            "PATCH_STRUCTURED_EMPTY_CHUNK: chunk must include at least one line.",
            details={"chunk_index": chunk_index},
        )
    lines = tuple(
        _parse_line(line_value, chunk_index, line_index)
        for line_index, line_value in enumerate(lines_value)
    )
    if not any(line.op in _EDIT_OPS for line in lines):
        raise StructuredArtifactPatchError(
            "PATCH_STRUCTURED_NO_EDIT: chunk must include at least one add or remove line.",
            details={"chunk_index": chunk_index},
        )
    return StructuredPatchChunk(lines=lines)


def _parse_line(
    value: object,
    chunk_index: int,
    line_index: int,
) -> StructuredPatchLine:
    if not isinstance(value, dict):
        raise RuntimeError("validated artifact_patch line must be an object")
    op_value = value.get("op")
    text_value = value.get("text")
    if not isinstance(op_value, str) or not isinstance(text_value, str):
        raise RuntimeError("validated artifact_patch line must include op and text")
    try:
        op = StructuredPatchLineOp(op_value)
    except ValueError as exc:
        raise RuntimeError("validated artifact_patch line has invalid op") from exc
    if "\n" in text_value or "\r" in text_value:
        raise StructuredArtifactPatchError(
            "PATCH_STRUCTURED_LINE_CONTAINS_NEWLINE: text must be one physical document line.",
            details={
                "chunk_index": chunk_index,
                "line_index": line_index,
                "op": op.value,
                "text": text_value,
            },
        )
    if op != StructuredPatchLineOp.ADD:
        _validate_current_document_line_pattern(
            text=text_value,
            chunk_index=chunk_index,
            line_index=line_index,
            op=op,
        )
    return StructuredPatchLine(op=op, text=text_value, line_index=line_index)


def _validate_current_document_line_pattern(
    *,
    text: str,
    chunk_index: int,
    line_index: int,
    op: StructuredPatchLineOp,
) -> None:
    marker_count = text.count(LINE_OMISSION_MARKER)
    if marker_count == 0:
        return
    if marker_count > 1:
        raise StructuredArtifactPatchError(
            (
                "PATCH_STRUCTURED_INVALID_OMISSION: context/remove text may "
                "include <OMITTED> at most once."
            ),
            details={
                "chunk_index": chunk_index,
                "line_index": line_index,
                "op": op.value,
                "text": text,
            },
        )

    prefix, suffix = text.split(LINE_OMISSION_MARKER)
    if prefix and suffix:
        return
    raise StructuredArtifactPatchError(
        (
            "PATCH_STRUCTURED_INVALID_OMISSION: <OMITTED> requires both prefix "
            "and suffix text."
        ),
        details={
            "chunk_index": chunk_index,
            "line_index": line_index,
            "op": op.value,
            "text": text,
        },
    )


def _split_text(text: str) -> tuple[list[str], bool]:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    if normalized == "":
        return [], False
    trailing_newline = normalized.endswith("\n")
    if trailing_newline:
        normalized = normalized[:-1]
    return normalized.split("\n") if normalized else [], trailing_newline


def _join_text(lines: list[str], *, trailing_newline: bool) -> str:
    if not lines:
        return "\n" if trailing_newline else ""
    return "\n".join(lines) + ("\n" if trailing_newline else "")


def _old_entries_for_chunk(
    chunk: StructuredPatchChunk,
) -> tuple[StructuredPatchLine, ...]:
    return tuple(line for line in chunk.lines if line.op in _CURRENT_DOCUMENT_OPS)


def _find_unique_ordered_span(
    *,
    current_lines: list[str],
    old_entries: tuple[StructuredPatchLine, ...],
    cursor: int,
    chunk_index: int,
) -> _OrderedChunkMatch:
    if not old_entries:
        if not current_lines:
            return _OrderedChunkMatch(positions_by_line_index={}, start=0, end=0)
        raise StructuredArtifactPatchError(
            "PATCH_CONTEXT_REQUIRED: chunk must include context or remove lines copied from the current document.",
            details={"chunk_index": chunk_index},
        )

    matches: list[_OrderedChunkMatch] = []
    _find_ordered_matches_from_start_candidates(
        current_lines=current_lines,
        old_entries=old_entries,
        cursor=cursor,
        matches=matches,
    )
    if len(matches) > 1:
        raise StructuredArtifactPatchError(
            "PATCH_CONTEXT_AMBIGUOUS: chunk matched multiple nearby locations; add more context lines.",
            details={
                "chunk_index": chunk_index,
                "old_lines": [
                    entry.text for entry in old_entries[:OLD_LINE_PREVIEW_LIMIT]
                ],
            },
        )
    if not matches:
        raise StructuredArtifactPatchError(
            "PATCH_CONTEXT_NOT_FOUND: chunk did not match a nearby ordered span in the current document content.",
            details=_context_not_found_details(
                current_lines=current_lines,
                old_entries=old_entries,
                chunk_index=chunk_index,
            ),
        )
    return matches[0]


def _find_ordered_matches_from_start_candidates(
    *,
    current_lines: list[str],
    old_entries: tuple[StructuredPatchLine, ...],
    cursor: int,
    matches: list[_OrderedChunkMatch],
) -> None:
    first_entry = old_entries[0]
    start_candidates_seen = 0
    for start_index in range(cursor, len(current_lines)):
        if not _line_matches_entry(current_lines[start_index], first_entry):
            continue
        start_candidates_seen += 1
        if start_candidates_seen > MAX_START_CANDIDATES:
            return

        match = _find_ordered_match_from_start(
            current_lines=current_lines,
            old_entries=old_entries,
            start_index=start_index,
        )
        if match is None:
            continue
        matches.append(match)
        if len(matches) > 1:
            return


def _find_ordered_match_from_start(
    *,
    current_lines: list[str],
    old_entries: tuple[StructuredPatchLine, ...],
    start_index: int,
) -> _OrderedChunkMatch | None:
    positions_by_line_index = {old_entries[0].line_index: start_index}
    previous_match_index = start_index
    for entry in old_entries[1:]:
        next_match_index = _find_next_ordered_entry_index(
            current_lines=current_lines,
            entry=entry,
            start_index=start_index,
            previous_match_index=previous_match_index,
        )
        if next_match_index is None:
            return None
        positions_by_line_index[entry.line_index] = next_match_index
        previous_match_index = next_match_index

    return _OrderedChunkMatch(
        positions_by_line_index=positions_by_line_index,
        start=start_index,
        end=previous_match_index + 1,
    )


def _find_next_ordered_entry_index(
    *,
    current_lines: list[str],
    entry: StructuredPatchLine,
    start_index: int,
    previous_match_index: int,
) -> int | None:
    search_end = min(
        previous_match_index + MAX_CONTEXT_GAP_LINES + 2,
        start_index + MAX_CHUNK_SPAN_LINES,
        len(current_lines),
    )
    for current_index in range(previous_match_index + 1, search_end):
        if _line_matches_entry(current_lines[current_index], entry):
            return current_index
    return None


def _line_matches_entry(current_line: str, entry: StructuredPatchLine) -> bool:
    if LINE_OMISSION_MARKER not in entry.text:
        return current_line == entry.text
    prefix, suffix = entry.text.split(LINE_OMISSION_MARKER)
    if len(current_line) < len(prefix) + len(suffix):
        return False
    return current_line.startswith(prefix) and current_line.endswith(suffix)


def _apply_chunk_at_match(
    *,
    current_lines: list[str],
    chunk: StructuredPatchChunk,
    match: _OrderedChunkMatch,
) -> tuple[list[str], int]:
    output_span: list[str] = []
    current_index = match.start
    for line in chunk.lines:
        if line.op == StructuredPatchLineOp.ADD:
            output_span.append(line.text)
            continue

        matched_index = match.positions_by_line_index[line.line_index]
        output_span.extend(current_lines[current_index:matched_index])
        if line.op == StructuredPatchLineOp.CONTEXT:
            output_span.append(current_lines[matched_index])
        current_index = matched_index + 1

    output_span.extend(current_lines[current_index : match.end])
    updated_lines = (
        current_lines[: match.start] + output_span + current_lines[match.end :]
    )
    return updated_lines, match.start + len(output_span)


def _context_not_found_details(
    *,
    current_lines: list[str],
    old_entries: tuple[StructuredPatchLine, ...],
    chunk_index: int,
) -> dict[str, JSONValue]:
    for entry in old_entries:
        if not any(
            _line_matches_entry(current_line, entry) for current_line in current_lines
        ):
            return {
                "chunk_index": chunk_index,
                "line_index": entry.line_index,
                "op": entry.op.value,
                "text": entry.text,
                "hint": (
                    "Copy context and remove text from the current document. Use "
                    "<OMITTED> only once inside a line when abbreviating the middle. "
                    "Markdown bullet markers belong in text; edit intent belongs in op."
                ),
            }
    return {
        "chunk_index": chunk_index,
        "old_lines": [entry.text for entry in old_entries[:OLD_LINE_PREVIEW_LIMIT]],
        "hint": (
            "The listed context/remove lines exist, but not in the same nearby "
            "ordered span."
        ),
    }


_CURRENT_DOCUMENT_OPS = frozenset(
    (StructuredPatchLineOp.CONTEXT, StructuredPatchLineOp.REMOVE)
)
_EDIT_OPS = frozenset((StructuredPatchLineOp.REMOVE, StructuredPatchLineOp.ADD))


__all__ = [
    "StructuredArtifactPatch",
    "StructuredArtifactPatchError",
    "StructuredPatchChunk",
    "StructuredPatchLine",
    "StructuredPatchLineOp",
    "apply_structured_artifact_patch",
    "parse_structured_artifact_patch_request",
]
