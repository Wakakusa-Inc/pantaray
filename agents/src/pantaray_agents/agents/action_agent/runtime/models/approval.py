"""Approval resume 境界モデル。"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator

from pantaray_agents.schema.agent.base import JSONValue

from .tool_call import ToolCallModel

ApprovalPendingOwnerModel = Literal["supervisor", "goal_worker"]


class PendingApprovalRequestModel(BaseModel):
    """承認待ち中の canonical pending request。"""

    model_config = ConfigDict(extra="forbid", strict=True)

    owner: ApprovalPendingOwnerModel
    tool_call: ToolCallModel
    approval_session_id: str
    tool_request_id: str
    requested_at: str
    intent_class: str
    command_summary: dict[str, JSONValue]
    goal_id: str | None = None
    thinking: str | None = None
    thinking_summary: str | None = None

    @field_validator(
        "approval_session_id",
        "tool_request_id",
        "requested_at",
        "intent_class",
    )
    @classmethod
    def _validate_required_strings(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("approval request fields must be non-empty strings.")
        return normalized

    @field_validator("goal_id")
    @classmethod
    def _normalize_goal_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @field_validator("thinking", "thinking_summary")
    @classmethod
    def _normalize_optional_strings(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    def __getitem__(self, key: str) -> object:
        return getattr(self, key)

    def get(self, key: str, default: object = None) -> object:
        return getattr(self, key, default)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, Mapping):
            return self.model_dump(mode="python") == dict(other)
        return super().__eq__(other)
