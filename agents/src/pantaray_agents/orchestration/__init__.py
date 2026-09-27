"""オーケストレーション層の公開エクスポート。"""

from __future__ import annotations

from typing import Any


def __getattr__(name: str) -> Any:
    if name == "orchestration_ws_router":
        from .router import ws_router

        return ws_router
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "orchestration_ws_router",
]
