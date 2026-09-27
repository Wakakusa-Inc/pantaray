from __future__ import annotations

from dataclasses import dataclass
from fnmatch import fnmatch

from .paths import ResolvedSandboxPath, SandboxPathError, SandboxPathErrorCode


@dataclass(frozen=True, slots=True)
class EditablePathPolicy:
    allowed_globs: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.allowed_globs:
            raise ValueError("allowed_globs must not be empty")

    def require_editable(self, resolved: ResolvedSandboxPath) -> None:
        relative_path = resolved.relative_path
        if self.allows(relative_path):
            return
        raise SandboxPathError(
            SandboxPathErrorCode.PATH_DENIED,
            f"path is outside editable policy: {relative_path}",
        )

    def allows(self, relative_path: str) -> bool:
        return any(
            fnmatch(relative_path, pattern) or fnmatch(f"{relative_path}/", pattern)
            for pattern in self.allowed_globs
        )
