"""ActionStepRecord の必須フィールド検証テスト。

short_step_id/local_step_number/goal_handle が必須であることを検証する。
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from pantaray_agents.schema.agent.action import ActionStepRecord


def test_action_step_record_requires_short_step_id() -> None:
    """ActionStepRecord が short_step_id を必須として拒否すること。"""
    data = {
        "step_id": "step-123",
        "action_id": "act-123",
        "step_number": 1,
        "step_name": "test",
        "step_type": "llm_output",
        "step_input": {},
        # short_step_id が欠落
    }

    with pytest.raises(ValidationError):
        ActionStepRecord(**data)


def test_action_step_record_requires_local_step_number() -> None:
    """ActionStepRecord が local_step_number を必須として拒否すること。"""
    data = {
        "step_id": "step-123",
        "action_id": "act-123",
        "step_number": 1,
        "step_name": "test",
        "step_type": "llm_output",
        "step_input": {},
        "short_step_id": "S-1-THINK",
        # local_step_number が欠落
    }

    with pytest.raises(ValidationError):
        ActionStepRecord(**data)


def test_action_step_record_requires_goal_handle() -> None:
    """ActionStepRecord が goal_handle を必須として拒否すること（Supervisor/Goal Worker いずれも）。"""
    data = {
        "step_id": "step-123",
        "action_id": "act-123",
        "step_number": 1,
        "step_name": "test",
        "step_type": "llm_output",
        "step_input": {},
        "short_step_id": "S-1-THINK",
        "local_step_number": 1,
        # goal_handle が欠落
    }

    with pytest.raises(ValidationError):
        ActionStepRecord(**data)


def test_action_step_record_accepts_valid_data() -> None:
    """ActionStepRecord が必須フィールドを含む有効なデータを受け入れること。"""
    data = {
        "step_id": "step-123",
        "action_id": "act-123",
        "step_number": 1,
        "step_name": "test",
        "step_type": "llm_output",
        "step_input": {},
        "short_step_id": "S-1-THINK",
        "local_step_number": 1,
        "goal_handle": "S",
    }

    record = ActionStepRecord(**data)
    assert record.short_step_id == "S-1-THINK"
    assert record.local_step_number == 1
    assert record.goal_handle == "S"


def test_action_step_record_accepts_goal_worker_goal_handle() -> None:
    """Goal Worker の goal_handle も有効であること。"""
    data = {
        "step_id": "step-456",
        "action_id": "act-123",
        "step_number": 2,
        "step_name": "goal_worker::react",
        "step_type": "llm_output",
        "step_input": {},
        "short_step_id": "G1-2-THINK",
        "local_step_number": 2,
        "goal_handle": "G1",
    }

    record = ActionStepRecord(**data)
    assert record.goal_handle == "G1"


def test_action_step_record_rejects_invalid_status() -> None:
    """ActionStepRecord は StepStatusType 外の status を拒否すること。"""
    data = {
        "step_id": "step-789",
        "action_id": "act-123",
        "step_number": 3,
        "step_name": "tool::invalid",
        "step_type": "tool_execution",
        "status": "warning",
        "short_step_id": "S-3-TOOL",
        "local_step_number": 3,
        "goal_handle": "S",
    }

    with pytest.raises(ValidationError):
        ActionStepRecord(**data)


def test_action_step_record_accepts_user_request_payload() -> None:
    record = ActionStepRecord(
        step_id="step-user-1",
        action_id="act-123",
        step_number=1,
        step_name="user_request",
        step_type="user_request",
        user_request_text="Implement the accepted request",
        short_step_id="S-1-USER",
        local_step_number=1,
        goal_handle="S",
    )

    assert record.user_request_text == "Implement the accepted request"


@pytest.mark.parametrize(
    ("user_request_text", "thinking"),
    [
        (None, None),
        ("   ", None),
        ("valid request", "not user input"),
    ],
)
def test_action_step_record_rejects_invalid_user_request_shape(
    user_request_text: str | None,
    thinking: str | None,
) -> None:
    with pytest.raises(ValidationError):
        ActionStepRecord(
            step_id="step-user-1",
            action_id="act-123",
            step_number=1,
            step_name="user_request",
            step_type="user_request",
            user_request_text=user_request_text,
            thinking=thinking,
            short_step_id="S-1-USER",
            local_step_number=1,
            goal_handle="S",
        )


def test_action_step_record_rejects_user_request_text_on_llm_step() -> None:
    with pytest.raises(ValidationError):
        ActionStepRecord(
            step_id="step-think-1",
            action_id="act-123",
            step_number=2,
            step_name="supervisor_think",
            step_type="llm_output",
            user_request_text="wrong payload",
            short_step_id="S-2-THINK",
            local_step_number=2,
            goal_handle="S",
        )


@pytest.mark.parametrize(
    "short_step_id",
    ["S-1-user", "S-1-THINK", "S-2-USER", "G1-1-USER"],
)
def test_action_step_record_rejects_noncanonical_user_request_short_id(
    short_step_id: str,
) -> None:
    with pytest.raises(ValidationError):
        ActionStepRecord(
            step_id="step-user-1",
            action_id="act-123",
            step_number=1,
            step_name="user_request",
            step_type="user_request",
            user_request_text="request",
            short_step_id=short_step_id,
            local_step_number=1,
            goal_handle="S",
        )
