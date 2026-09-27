from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Literal

PatchOp = Literal["context", "remove", "add"]

MAX_PATCH_CHUNKS = 50
MAX_PATCH_LINES_PER_CHUNK = 80
MAX_PATCH_TOTAL_LINES = 800


class MemoryPatchErrorCode(StrEnum):
    CONTEXT_NOT_FOUND = "CONTEXT_NOT_FOUND"
    CONTEXT_AMBIGUOUS = "CONTEXT_AMBIGUOUS"
    INVALID_PATCH = "INVALID_PATCH"


class MemoryPatchError(ValueError):
    def __init__(self, code: MemoryPatchErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class PatchLine:
    op: PatchOp
    text: str


@dataclass(frozen=True, slots=True)
class PatchChunk:
    lines: tuple[PatchLine, ...]


def apply_memory_patch(base_text: str, chunks: tuple[PatchChunk, ...]) -> str:
    _validate_chunks(chunks)
    lines, trailing_newline = _split_raw_lines(base_text)
    cursor = 0
    for chunk in chunks:
        before, after = _chunk_patterns(chunk)
        start = _find_unique_chunk_start(lines=lines, pattern=before, cursor=cursor)
        end = start + len(before)
        lines[start:end] = after
        cursor = start + len(after)
    return _join_raw_lines(lines=lines, trailing_newline=trailing_newline)


def retry_advice_for_patch_error(code: MemoryPatchErrorCode, message: str) -> str:
    if code == MemoryPatchErrorCode.CONTEXT_NOT_FOUND:
        return (
            "Re-read the target file and copy context/remove lines from the raw "
            "file text before retrying."
        )
    if code == MemoryPatchErrorCode.CONTEXT_AMBIGUOUS:
        return "Add enough surrounding context lines to identify one location."
    if "limit" in message.lower() or "too broad" in message.lower():
        return (
            "Split the work into smaller section-level patches and apply them "
            "sequentially."
        )
    return "Fix the patch structure and retry with valid chunks and line ops."


def _validate_chunks(chunks: tuple[PatchChunk, ...]) -> None:
    if not chunks:
        raise MemoryPatchError(
            MemoryPatchErrorCode.INVALID_PATCH,
            "patch must contain at least one chunk",
        )
    if len(chunks) > MAX_PATCH_CHUNKS:
        raise MemoryPatchError(
            MemoryPatchErrorCode.INVALID_PATCH,
            "patch exceeds chunk limit",
        )
    total_lines = 0
    for chunk in chunks:
        if not chunk.lines:
            raise MemoryPatchError(
                MemoryPatchErrorCode.INVALID_PATCH,
                "chunk must contain at least one line",
            )
        if len(chunk.lines) > MAX_PATCH_LINES_PER_CHUNK:
            raise MemoryPatchError(
                MemoryPatchErrorCode.INVALID_PATCH,
                "chunk exceeds line limit",
            )
        if not any(line.op in ("remove", "add") for line in chunk.lines):
            raise MemoryPatchError(
                MemoryPatchErrorCode.INVALID_PATCH,
                "chunk must contain add or remove lines",
            )
        for line in chunk.lines:
            if line.op not in ("context", "remove", "add"):
                raise MemoryPatchError(
                    MemoryPatchErrorCode.INVALID_PATCH,
                    f"invalid patch op: {line.op}",
                )
            if "\n" in line.text or "\r" in line.text:
                raise MemoryPatchError(
                    MemoryPatchErrorCode.INVALID_PATCH,
                    "patch line text must not contain newline characters",
                )
            total_lines += 1
    if total_lines > MAX_PATCH_TOTAL_LINES:
        raise MemoryPatchError(
            MemoryPatchErrorCode.INVALID_PATCH,
            "patch exceeds total line limit",
        )


def _chunk_patterns(chunk: PatchChunk) -> tuple[list[str], list[str]]:
    before: list[str] = []
    after: list[str] = []
    for line in chunk.lines:
        if line.op in ("context", "remove"):
            before.append(line.text)
        if line.op in ("context", "add"):
            after.append(line.text)
    return before, after


def _find_unique_chunk_start(
    *,
    lines: list[str],
    pattern: list[str],
    cursor: int,
) -> int:
    if not pattern:
        return cursor
    matches = [
        index
        for index in range(cursor, len(lines) - len(pattern) + 1)
        if lines[index : index + len(pattern)] == pattern
    ]
    if not matches:
        raise MemoryPatchError(
            MemoryPatchErrorCode.CONTEXT_NOT_FOUND,
            "context/remove lines do not match current raw file text",
        )
    if len(matches) > 1:
        raise MemoryPatchError(
            MemoryPatchErrorCode.CONTEXT_AMBIGUOUS,
            "context/remove lines match multiple locations",
        )
    return matches[0]


def _split_raw_lines(text: str) -> tuple[list[str], bool]:
    if text == "":
        return [], False
    trailing_newline = text.endswith("\n")
    lines = text.split("\n")
    if trailing_newline:
        lines = lines[:-1]
    return lines, trailing_newline


def _join_raw_lines(*, lines: list[str], trailing_newline: bool) -> str:
    joined = "\n".join(lines)
    return f"{joined}\n" if trailing_newline else joined
