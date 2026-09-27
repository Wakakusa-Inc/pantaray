"""WebSocket の同時接続数の上限（in-process best-effort）を管理する。

前提/制約:
    - 本実装は **単一プロセス内** のカウンタであり、複数インスタンス（水平スケール）では
      合算上限を保証できない。
    - 複数インスタンスで厳格に制限する場合は、共有ストアでカウンタを管理する。
"""

from __future__ import annotations

import threading
from collections import defaultdict
from dataclasses import dataclass

from pantaray_agents.config_tunables import load_local_runtime_tunables

_lock = threading.Lock()

# --- Active connections (per-process) ---
_active_connections_total: int = 0
_active_connections_by_user: dict[str, int] = defaultdict(int)


@dataclass(frozen=True)
class WSCapacityLimits:
    """WS の接続数制限設定（すべて正の上限値）。"""

    max_connections_total: int
    max_connections_per_user: int


def load_ws_capacity_limits() -> WSCapacityLimits:
    """checked-in tunables から WS の容量制限を読み取る。"""
    cfg = load_local_runtime_tunables().websocket_capacity
    return WSCapacityLimits(
        max_connections_total=cfg.max_connections_total,
        max_connections_per_user=cfg.max_connections_per_user,
    )


def try_acquire_connection(*, user_id: str, limits: WSCapacityLimits) -> bool:
    """WS 接続枠を確保する（失敗時は False）。"""
    if not isinstance(user_id, str) or not user_id:
        return False
    global _active_connections_total  # noqa: PLW0603
    with _lock:
        if _active_connections_total >= limits.max_connections_total:
            return False
        if _active_connections_by_user[user_id] >= limits.max_connections_per_user:
            return False
        _active_connections_total += 1
        _active_connections_by_user[user_id] += 1
        return True


def release_connection(*, user_id: str) -> None:
    """WS 接続枠を解放する（best-effort）。"""
    if not isinstance(user_id, str) or not user_id:
        return
    with _lock:
        global _active_connections_total  # noqa: PLW0603
        if _active_connections_total > 0:
            _active_connections_total -= 1
        if _active_connections_by_user[user_id] > 0:
            _active_connections_by_user[user_id] -= 1
        if _active_connections_by_user[user_id] <= 0:
            _active_connections_by_user.pop(user_id, None)
