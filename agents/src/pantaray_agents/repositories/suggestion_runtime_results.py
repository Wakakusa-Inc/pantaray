from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from pantaray_agents.action_status import ActionTerminalStatus
from pantaray_agents.schema.repositories.repository import DBRow


@dataclass(frozen=True)
class AppendProcessEventResult:
    """公開 process event append の結果。"""

    sequence: int
    inserted: bool


@dataclass(frozen=True)
class FinalizeActionTerminalAndProjectHistoryResult:
    """Action runtime terminalization transaction の結果。"""

    process_completed_sequence: int
    action_status: ActionTerminalStatus
    action_failure_code: str | None = None
    final_output: str | None = None
    failure_stage: str | None = None
    failure_message_public: str | None = None


@dataclass(frozen=True)
class ActionToolApprovalDecisionResult:
    """Action tool approval decision の durable 反映結果。"""

    decision: Literal["approved_once", "denied"]
    process_id: str | None = None
    job_id: str | None = None
    sequence: int | None = None


@dataclass(frozen=True)
class FinalizeActionErrorResult:
    """Action start failure の最終状態収束結果。"""

    outcome: Literal["updated", "already_error", "superseded", "not_found"]
    row: DBRow | None


@dataclass(frozen=True)
class FinalizeActionTerminalResult:
    """Action terminal 状態の CAS 更新結果。"""

    outcome: Literal["updated", "already_terminal", "superseded", "not_found"]
    row: DBRow | None


@dataclass(frozen=True)
class FinalizeSuggestionTerminalResult:
    """Suggestion terminal 状態の CAS 更新結果。"""

    outcome: Literal["updated", "already_terminal", "not_found"]
    row: DBRow | None


@dataclass(frozen=True)
class FinalizeSuggestionStartErrorResult:
    """Suggestion start failure の最終状態収束結果。"""

    outcome: Literal["updated", "already_terminal", "not_found"]
    row: DBRow | None


@dataclass(frozen=True)
class AcceptActionCommandResult:
    """Action command の受理 CAS 結果。"""

    outcome: Literal["updated", "already_same_command", "conflict", "not_found"]
    row: DBRow | None


@dataclass(frozen=True)
class StartActionTransitionResult:
    """Action start phase 遷移の CAS 結果。"""

    outcome: Literal[
        "updated",
        "already_processing",
        "already_terminal",
        "superseded",
        "not_found",
    ]
    row: DBRow | None
