"""WS handler shared types."""

from __future__ import annotations

from typing import TypedDict


class SuggestionStatusPersistenceError(RuntimeError):
    """Suggestion/action 状態の strict 永続化失敗。"""


class ProcessMetadata(TypedDict, total=False):
    """プロセスの種類や関連IDを保持するメタデータ。"""

    kind: str
    suggestion_id: str | None
    action_id: str | None
    command_id: str | None
