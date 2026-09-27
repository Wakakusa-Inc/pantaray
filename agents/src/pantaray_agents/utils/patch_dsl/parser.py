from __future__ import annotations

from pathlib import PurePosixPath

from .errors import PatchDslParseError, PatchDslPathError
from .models import PatchChange, PatchChunk, PatchOperation, PatchSet

BEGIN_PATCH = "*** Begin Patch"
END_PATCH = "*** End Patch"
ADD_FILE = "*** Add File: "
DELETE_FILE = "*** Delete File: "
UPDATE_FILE = "*** Update File: "
MOVE_TO = "*** Move to: "
CHUNK_HEADER = "@@"


def is_patch_dsl(patch_text: str) -> bool:
    normalized = patch_text.replace("\r\n", "\n").replace("\r", "\n").strip("\n")
    if not normalized.strip():
        return False
    return normalized.split("\n", 1)[0] == BEGIN_PATCH


def has_patch_dsl_markers(patch_text: str) -> bool:
    normalized = patch_text.replace("\r\n", "\n").replace("\r", "\n").strip("\n")
    if not normalized.strip():
        return False
    return any(
        line.startswith(BEGIN_PATCH)
        or line.startswith(END_PATCH)
        or line.startswith(ADD_FILE)
        or line.startswith(DELETE_FILE)
        or line.startswith(UPDATE_FILE)
        or line.startswith(MOVE_TO)
        for line in normalized.split("\n")
    )


def extract_patch_dsl_paths(patch_text: str) -> tuple[str, ...]:
    paths: list[str] = []
    for change in parse_patch_dsl(patch_text).changes:
        for path in (change.path, change.move_path):
            if path is not None and path not in paths:
                paths.append(path)
    return tuple(paths)


def parse_patch_dsl(patch_text: str) -> PatchSet:
    lines = _normalize_lines(patch_text)
    if len(lines) < 2 or lines[0] != BEGIN_PATCH or lines[-1] != END_PATCH:
        raise PatchDslParseError(
            "PATCH_DSL_ENVELOPE_ERROR: patch must start with "
            "'*** Begin Patch' and end with '*** End Patch'."
        )
    index = 1
    changes: list[PatchChange] = []
    while index < len(lines) - 1:
        line = lines[index]
        if line.startswith(ADD_FILE):
            change, index = _parse_add(lines=lines, index=index)
        elif line.startswith(DELETE_FILE):
            change, index = _parse_delete(lines=lines, index=index)
        elif line.startswith(UPDATE_FILE):
            change, index = _parse_update(lines=lines, index=index)
        else:
            raise PatchDslParseError(
                f"PATCH_DSL_EXPECTED_FILE_HEADER: expected file operation at line {index + 1}."
            )
        changes.append(change)

    if not changes:
        raise PatchDslParseError(
            "PATCH_DSL_EMPTY: patch must contain at least one change."
        )
    return PatchSet(changes=tuple(changes))


def _normalize_lines(patch_text: str) -> list[str]:
    normalized = patch_text.replace("\r\n", "\n").replace("\r", "\n").strip("\n")
    if not normalized.strip():
        raise PatchDslParseError("PATCH_DSL_EMPTY: patch text is empty.")
    return normalized.split("\n")


def _parse_add(*, lines: list[str], index: int) -> tuple[PatchChange, int]:
    path = _parse_path(lines[index], ADD_FILE)
    index += 1
    content_lines: list[str] = []
    while index < len(lines) - 1 and not _is_file_header(lines[index]):
        line = lines[index]
        if not line.startswith("+"):
            raise PatchDslParseError(
                f"PATCH_DSL_ADD_LINE_PREFIX: add file content at line {index + 1} must start with '+'."
            )
        content_lines.append(line[1:])
        index += 1
    return (
        PatchChange(
            operation=PatchOperation.ADD,
            path=path,
            contents=_join_patch_content(content_lines),
        ),
        index,
    )


def _parse_delete(*, lines: list[str], index: int) -> tuple[PatchChange, int]:
    path = _parse_path(lines[index], DELETE_FILE)
    index += 1
    if index < len(lines) - 1 and not _is_file_header(lines[index]):
        raise PatchDslParseError(
            f"PATCH_DSL_DELETE_BODY: delete file at line {index} must not include body lines."
        )
    return PatchChange(operation=PatchOperation.DELETE, path=path), index


def _parse_update(*, lines: list[str], index: int) -> tuple[PatchChange, int]:
    path = _parse_path(lines[index], UPDATE_FILE)
    index += 1
    move_path: str | None = None
    if index < len(lines) - 1 and lines[index].startswith(MOVE_TO):
        move_path = _parse_path(lines[index], MOVE_TO)
        index += 1

    chunks: list[PatchChunk] = []
    current_chunk: list[str] | None = None
    while index < len(lines) - 1 and not _is_file_header(lines[index]):
        line = lines[index]
        if line == CHUNK_HEADER or line.startswith(f"{CHUNK_HEADER} "):
            if current_chunk is not None:
                chunks.append(_build_chunk(current_chunk))
            current_chunk = []
            index += 1
            continue
        if current_chunk is None:
            raise PatchDslParseError(
                f"PATCH_DSL_MISSING_CHUNK: update body at line {index + 1} must start with '@@'."
            )
        if not line.startswith((" ", "+", "-")):
            raise PatchDslParseError(
                f"PATCH_DSL_BAD_LINE_PREFIX: update line {index + 1} must start with space, '+', or '-'."
            )
        current_chunk.append(line)
        index += 1

    if current_chunk is not None:
        chunks.append(_build_chunk(current_chunk))
    if not chunks:
        raise PatchDslParseError(
            "PATCH_DSL_MISSING_CHUNK: update must include at least one '@@' chunk."
        )

    return (
        PatchChange(
            operation=PatchOperation.MOVE
            if move_path is not None
            else PatchOperation.UPDATE,
            path=path,
            chunks=tuple(chunks),
            move_path=move_path,
        ),
        index,
    )


def _build_chunk(lines: list[str]) -> PatchChunk:
    if not lines:
        raise PatchDslParseError("PATCH_DSL_EMPTY_CHUNK: '@@' chunk must not be empty.")
    if not any(line.startswith(("+", "-")) for line in lines):
        raise PatchDslParseError(
            "PATCH_DSL_NO_EDIT: update chunk must add or remove at least one line."
        )
    return PatchChunk(lines=tuple(lines))


def _parse_path(line: str, prefix: str) -> str:
    raw_path = line.removeprefix(prefix)
    return _validate_patch_path(raw_path)


def _validate_patch_path(raw_path: str) -> str:
    path = raw_path.strip()
    if not path:
        raise PatchDslPathError("PATCH_DSL_PATH_EMPTY: patch path must not be empty.")
    pure = PurePosixPath(path)
    if path.startswith("~"):
        raise PatchDslPathError(
            "PATCH_DSL_PATH_UNSAFE: patch path must not use shell home expansion."
        )
    if ".." in pure.parts:
        raise PatchDslPathError(
            "PATCH_DSL_PATH_UNSAFE: patch path must not contain '..'."
        )
    parts = path.split("/")
    if path.startswith("/"):
        parts = parts[1:]
    if any(part == "" for part in parts):
        raise PatchDslPathError(
            "PATCH_DSL_PATH_UNSAFE: patch path contains an empty segment."
        )
    return path


def _is_file_header(line: str) -> bool:
    return line.startswith((ADD_FILE, DELETE_FILE, UPDATE_FILE))


def _join_patch_content(lines: list[str]) -> str:
    if not lines:
        return ""
    return "\n".join(lines) + "\n"
