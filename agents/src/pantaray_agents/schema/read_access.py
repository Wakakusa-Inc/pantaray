from __future__ import annotations

from typing import Literal

READ_ACCESS_SCOPE_WORKSPACE: Literal["workspace"] = "workspace"
READ_ACCESS_SCOPE_FULL_ACCESS: Literal["full_access"] = "full_access"
ReadAccessScope = Literal["workspace", "full_access"]

__all__ = [
    "READ_ACCESS_SCOPE_FULL_ACCESS",
    "READ_ACCESS_SCOPE_WORKSPACE",
    "ReadAccessScope",
]
