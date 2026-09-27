"""ActionAgent tool call 境界モデル。"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from pantaray_agents.schema.action_tool_call import ActionToolCallOrigin
from pantaray_agents.schema.agent.base import JSONValue

ActionLifecyclePhaseModel = Literal[
    "init",
    "planning",
    "executing",
    "finalizing",
]

ToolBatchModeModel = Literal["parallel", "sequential"]


class ToolCallModel(BaseModel):
    """ツール呼び出しの canonical input。"""

    model_config = ConfigDict(extra="forbid", strict=True)

    tool_id: str
    args: dict[str, JSONValue]

    @field_validator("tool_id")
    @classmethod
    def _validate_tool_id(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("tool_id must be a non-empty string.")
        return normalized

    def __getitem__(self, key: str) -> JSONValue:
        if key == "tool_id":
            return self.tool_id
        if key == "args":
            return self.args
        raise KeyError(key)

    def get(self, key: str, default: JSONValue | None = None) -> JSONValue | None:
        try:
            return self[key]
        except KeyError:
            return default

    def __eq__(self, other: object) -> bool:
        if isinstance(other, ToolCallModel):
            return self.tool_id == other.tool_id and self.args == other.args
        if isinstance(other, Mapping):
            return {"tool_id": self.tool_id, "args": self.args} == dict(other)
        return False


class PendingToolCallModel(BaseModel):
    """バッチ内の 1 呼び出しと、その呼び出しが履歴へ残す ``step_note``。

    ``step_note`` は Supervisor が呼び出しごとに書く「状況→判断→行動」で、ハンドラへは
    渡さない。バッチでは呼び出しごとに異なるため、THINK 行の要約とは別に呼び出しへ
    束ねて持ち回る。
    """

    model_config = ConfigDict(extra="forbid", strict=True)

    call: ToolCallModel
    step_note: str
    origin: ActionToolCallOrigin

    @property
    def tool_id(self) -> str:
        return self.call.tool_id

    @field_validator("step_note")
    @classmethod
    def _validate_step_note(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("step_note must be a non-empty string.")
        return normalized


class PendingToolBatchModel(BaseModel):
    """1 回の THINK が決めた、宣言順のツール呼び出し列。"""

    model_config = ConfigDict(extra="forbid", strict=True)

    calls: tuple[PendingToolCallModel, ...]
    mode: ToolBatchModeModel

    @field_validator("calls", mode="before")
    @classmethod
    def _normalize_json_calls(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value

    @field_validator("calls")
    @classmethod
    def _validate_calls(
        cls, value: tuple[PendingToolCallModel, ...]
    ) -> tuple[PendingToolCallModel, ...]:
        if not value:
            raise ValueError("calls must contain at least one tool call.")
        return value


class NextActionModel(BaseModel):
    """Supervisor の未消費 decision。

    ``batch`` がバッチ全体の正本で、``tool`` はその先頭要素の射影である。単発実行しか
    消費しない経路（checkpoint 復元・承認再開）は ``tool`` だけを読めばよい。
    """

    model_config = ConfigDict(extra="forbid", strict=True)

    tool: ToolCallModel | None = None
    batch: PendingToolBatchModel | None = None
    decided_at: str

    @model_validator(mode="after")
    def _validate_batch_projection(self) -> NextActionModel:
        if self.batch is not None and self.tool != self.batch.calls[0].call:
            raise ValueError("tool must project the first call of batch.")
        if (
            self.batch is None
            and self.tool is not None
            and self.tool.tool_id == "spawn_subagent"
        ):
            raise ValueError("spawn_subagent requires an adopted call origin.")
        return self

    @field_validator("decided_at")
    @classmethod
    def _validate_decided_at(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("decided_at must be a non-empty string.")
        return normalized

    def __getitem__(
        self, key: str
    ) -> JSONValue | ToolCallModel | PendingToolBatchModel | None:
        if key == "tool":
            return self.tool
        if key == "batch":
            return self.batch
        if key == "decided_at":
            return self.decided_at
        raise KeyError(key)

    def get(
        self,
        key: str,
        default: JSONValue | ToolCallModel | PendingToolBatchModel | None = None,
    ) -> JSONValue | ToolCallModel | PendingToolBatchModel | None:
        try:
            return self[key]
        except KeyError:
            return default

    def _identity(self) -> dict[str, object]:
        return {"tool": self.tool, "batch": self.batch, "decided_at": self.decided_at}

    def __eq__(self, other: object) -> bool:
        if isinstance(other, NextActionModel):
            return self._identity() == other._identity()
        if isinstance(other, Mapping):
            return self._identity() == dict(other)
        return False
