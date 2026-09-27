from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, TypedDict

ACTION_SUBAGENT_MAX_ACTIVE_CHILDREN_PER_PARENT = 4


class ActionSubagentWaitSuccess(TypedDict):
    child_process_id: str
    status: Literal["success"]
    report: str


class ActionSubagentWaitFailure(TypedDict):
    child_process_id: str
    status: Literal["failure"]
    error_code: str


class ActionSubagentWaitCanceled(TypedDict):
    child_process_id: str
    status: Literal["canceled"]


class ActionSubagentWaitNonterminal(TypedDict):
    child_process_id: str
    status: Literal["nonterminal"]


type ActionSubagentWaitResult = (
    ActionSubagentWaitSuccess
    | ActionSubagentWaitFailure
    | ActionSubagentWaitCanceled
    | ActionSubagentWaitNonterminal
)


@dataclass(frozen=True, slots=True)
class ActionSubagentWaitRequest:
    user_id: str
    action_id: str
    parent_process_id: str
    parent_job_id: str
    child_process_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ActionSubagentCollectionReceipt:
    request: ActionSubagentWaitRequest
    collected_at: str
