from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class PatchOperation(StrEnum):
    ADD = "add"
    UPDATE = "update"
    DELETE = "delete"
    MOVE = "move"


@dataclass(frozen=True, slots=True)
class PatchChunk:
    lines: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PatchChange:
    operation: PatchOperation
    path: str
    chunks: tuple[PatchChunk, ...] = ()
    contents: str = ""
    move_path: str | None = None


@dataclass(frozen=True, slots=True)
class PatchSet:
    changes: tuple[PatchChange, ...]


@dataclass(frozen=True, slots=True)
class PatchFileChange:
    operation: PatchOperation
    path: str
    old_text: str
    new_text: str
    move_path: str | None = None
