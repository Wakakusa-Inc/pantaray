"""採用したActionのツール呼び出しを、実行attemptと独立して識別する。"""

from pydantic import BaseModel, ConfigDict, Field


class ActionToolCallOrigin(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    llm_step_id: str = Field(min_length=1)
    call_id: str = Field(min_length=1)
