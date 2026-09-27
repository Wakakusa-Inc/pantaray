"""Action Agent の severity 関連定数。"""

from __future__ import annotations

from typing import Final, Literal

NON_FATAL_SEVERITIES: Final[frozenset[str]] = frozenset({"warning", "info"})
FATAL_SEVERITIES: Final[frozenset[str]] = frozenset({"error", "critical"})

NON_FATAL_ERROR_STEP_NAME: Final[str] = "action::warning"
NON_FATAL_ERROR_STEP_STATUS: Final[Literal["success"]] = "success"

__all__ = [
    "FATAL_SEVERITIES",
    "NON_FATAL_ERROR_STEP_NAME",
    "NON_FATAL_ERROR_STEP_STATUS",
    "NON_FATAL_SEVERITIES",
]
