"""Action 系 WS error の top-level meta 型定義。"""

from __future__ import annotations

from typing import Literal, NotRequired, TypedDict

ActionErrorStage = Literal[
    "preflight_rejected",
    "start_failed",
    "running_failed",
    "persist_final_state_failed",
]


class ActionErrorMeta(TypedDict):
    """Action 系 error の top-level meta。

    注意:
        `ErrorMessage.metadata` ではなく、WS payload top-level の `meta` を SSOT とする。
    """

    kind: Literal["action"]
    suggestion_id: str
    command_id: str
    stage: ActionErrorStage
    process_id: NotRequired[str]
    action_id: NotRequired[str]
    failure_kind: NotRequired[str]
    error_code: str


__all__ = ["ActionErrorMeta", "ActionErrorStage"]
