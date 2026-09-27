from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

MEMORY_RUN_TOOL_RESULTS_DIRNAME = "tool-results"


@dataclass(frozen=True, slots=True)
class MemoryRunWorkspace:
    """Filesystem storage exclusively owned by one Memory harness run."""

    root_path: Path
    tool_results_path: Path

    @classmethod
    def from_root_path(cls, root_path: Path) -> MemoryRunWorkspace:
        return cls(
            root_path=root_path,
            tool_results_path=root_path / MEMORY_RUN_TOOL_RESULTS_DIRNAME,
        )


__all__ = [
    "MEMORY_RUN_TOOL_RESULTS_DIRNAME",
    "MemoryRunWorkspace",
]
