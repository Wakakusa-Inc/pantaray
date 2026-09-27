from __future__ import annotations

import json
from pathlib import Path
from typing import cast

import pytest
from tests.unit.agents.action_agent.fixtures import base_state

from pantaray_agents.agents.action_agent import ActionAgent
from pantaray_agents.agents.action_agent.runtime.handlers.tools import (
    ToolValidationError,
    _run_history_fetch,
)
from pantaray_agents.agents.action_agent.tools import HISTORY_FETCH_TOOL
from pantaray_agents.local_runtime.tooling.tool_result_storage import (
    ACTION_TOOL_RESULT_INLINE_CHARACTER_LIMIT,
    store_tool_result,
)
from pantaray_agents.schema.agent.base import JSONValue
from pantaray_agents.schema.repositories.repository import DBRow, RepositoryResult
from pantaray_agents.schema.tool_result import serialize_json_tool_output


@pytest.mark.asyncio
@pytest.mark.usefixtures("tokyo_local_zone")
async def test_history_fetch_returns_mixed_steps_in_requested_order_without_uuid(
    action_agent: ActionAgent,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_get_action_steps_by_short_step_ids(
        *, user_id: str, action_id: str, short_step_ids: tuple[str, ...]
    ) -> RepositoryResult[list[DBRow]]:
        assert user_id
        assert action_id
        assert short_step_ids == ("S-1-USER", "S-2-THINK", "G1-3-TOOL")
        return RepositoryResult(
            data=[
                _row("G1-3-TOOL", 3, "tool_execution", tool_output={"ok": True}),
                _row("S-1-USER", 1, "user_request", user_request_text="request"),
                _row("S-2-THINK", 2, "llm_output", thinking="reasoning"),
            ]
        )

    monkeypatch.setattr(
        action_agent.repository,
        "get_action_steps_by_short_step_ids",
        fake_get_action_steps_by_short_step_ids,
    )
    result = await _run_history_fetch(
        action_agent,
        step_id="internal-fetch-step",
        tool_def=HISTORY_FETCH_TOOL,
        args={"refs": ["S-1-USER", "S-2-THINK", "G1-3-TOOL"]},
        state=base_state(action_agent),
    )

    assert result.output["next_cursor"] is None
    steps = json.loads(result.output["content"])["steps"]
    assert [step["short_step_id"] for step in steps] == [
        "S-1-USER",
        "S-2-THINK",
        "G1-3-TOOL",
    ]
    assert steps[0]["user_request_text"] == "request"
    assert steps[1]["thinking"] == "reasoning"
    assert steps[2]["tool_output"] == {"ok": True}
    assert all("step_id" not in step for step in steps)
    assert all("action_id" not in step for step in steps)
    assert all("runtime_state_checkpoint" not in step for step in steps)
    # Stored UTC; the model reads the user's wall clock.
    assert steps[0]["started_at"] == "2026-09-27T06:50+09:00"
    assert steps[0]["completed_at"] == "2026-09-27T06:51+09:00"


@pytest.mark.asyncio
async def test_history_fetch_fails_closed_when_any_ref_is_missing(
    action_agent: ActionAgent,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_get_action_steps_by_short_step_ids(
        *, user_id: str, action_id: str, short_step_ids: tuple[str, ...]
    ) -> RepositoryResult[list[DBRow]]:
        assert user_id
        assert action_id
        assert short_step_ids
        return RepositoryResult(data=[_row("S-1-USER", 1, "user_request")])

    monkeypatch.setattr(
        action_agent.repository,
        "get_action_steps_by_short_step_ids",
        fake_get_action_steps_by_short_step_ids,
    )

    with pytest.raises(ToolValidationError) as exc_info:
        await _run_history_fetch(
            action_agent,
            step_id="internal-fetch-step",
            tool_def=HISTORY_FETCH_TOOL,
            args={"refs": ["S-1-USER", "S-2-THINK", "S-3-TOOL"]},
            state=base_state(action_agent),
        )

    assert str(exc_info.value) == (
        "history_fetch: refs not found in this Action: S-2-THINK, S-3-TOOL"
    )
    assert exc_info.value.details is not None
    assert exc_info.value.details["metadata"] == {
        "missing_refs": ["S-2-THINK", "S-3-TOOL"]
    }


def _row(
    short_step_id: str,
    step_number: int,
    step_type: str,
    *,
    user_request_text: str | None = None,
    thinking: str | None = None,
    tool_output: dict[str, JSONValue] | None = None,
) -> DBRow:
    return {
        "step_id": "d41363fb-9dd2-46bb-b9ba-5ac7c9f581df",
        "action_id": "act-123",
        "short_step_id": short_step_id,
        "step_number": step_number,
        "local_step_number": step_number,
        "step_name": "user_request" if step_type == "user_request" else "step",
        "step_type": step_type,
        "status": "success",
        "user_request_text": user_request_text,
        "thinking": thinking,
        "llm_prompt_text": None,
        "llm_response_text": None,
        "tool_args": None,
        "tool_output": tool_output,
        "error": None,
        "goal_handle": "S",
        "started_at": "2026-09-26T21:50:00.000000Z",
        "completed_at": "2026-09-26T21:51:30.000000Z",
        "runtime_state_checkpoint": {"secret": "not exposed"},
    }


@pytest.mark.asyncio
@pytest.mark.usefixtures("tokyo_local_zone")
@pytest.mark.parametrize("source_kind", ["many_tools", "large_think"])
async def test_history_fetch_pages_survive_storage_and_reassemble_exact_content(
    action_agent: ActionAgent,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    source_kind: str,
) -> None:
    if source_kind == "many_tools":
        rows = [
            _row(
                f"S-{index}-TOOL",
                index,
                "tool_execution",
                tool_output={
                    "schema_version": 1,
                    "status": "success",
                    "output": {"content": ('日本語😀\t"\\line\n' * 1_100)},
                    "output_storage_kind": "inline_json",
                    "output_owner_kind": "tool_invocation",
                },
            )
            for index in (1, 2, 3)
        ]
    else:
        rows = [_row("S-1-THINK", 1, "llm_output")]
        rows[0]["llm_prompt_text"] = "Prompt evidence\n" * 5_000
    refs = [str(row["short_step_id"]) for row in rows]

    async def fetch(**_kwargs) -> RepositoryResult[list[DBRow]]:
        return RepositoryResult(data=list(reversed(rows)))

    monkeypatch.setattr(
        action_agent.repository, "get_action_steps_by_short_step_ids", fetch
    )
    state = base_state(action_agent)
    cursor = None
    parts: list[str] = []
    offset = 0
    while True:
        result = await _run_history_fetch(
            action_agent,
            step_id="fetch-page",
            tool_def=HISTORY_FETCH_TOOL,
            args={"refs": refs, "cursor": cursor},
            state=state,
        )
        output = result.output
        assert (
            len(serialize_json_tool_output(output))
            <= ACTION_TOOL_RESULT_INLINE_CHARACTER_LIMIT
        )
        stored = store_tool_result(
            action_tool_results_path=tmp_path,
            invocation_id=f"page-{len(parts)}",
            output=output,
        )
        assert stored.storage_kind == "inline_json"
        page = cast(dict[str, JSONValue], stored.output_json)
        assert page["refs"] == refs
        assert page["offset"] == offset
        text = cast(str, page["content"])
        assert text
        parts.append(text)
        offset += len(text)
        cursor = page["next_cursor"]
        if cursor is None:
            assert offset == page["total_characters"]
            break
    expected = [
        {
            **{
                key: value
                for key, value in row.items()
                if key not in {"step_id", "action_id", "runtime_state_checkpoint"}
            },
            "started_at": "2026-09-27T06:50+09:00",
            "completed_at": "2026-09-27T06:51+09:00",
        }
        for row in rows
    ]
    assert len(parts) > 1
    assert json.loads("".join(parts)) == {"steps": expected}


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["content", "action", "offset"])
async def test_history_fetch_rejects_a_cursor_for_different_content_or_position(
    action_agent: ActionAgent,
    monkeypatch: pytest.MonkeyPatch,
    change: str,
) -> None:
    row = _row("S-1-THINK", 1, "llm_output", thinking="evidence " * 4_000)

    async def fetch(**_kwargs) -> RepositoryResult[list[DBRow]]:
        return RepositoryResult(data=[row])

    monkeypatch.setattr(
        action_agent.repository, "get_action_steps_by_short_step_ids", fetch
    )
    state = base_state(action_agent)
    result = await _run_history_fetch(
        action_agent,
        step_id="first-page",
        tool_def=HISTORY_FETCH_TOOL,
        args={"refs": ["S-1-THINK"]},
        state=state,
    )
    cursor = result.output["next_cursor"]
    assert cursor is not None
    if change == "content":
        row["thinking"] = "Repaired content " * 4_000
    elif change == "action":
        state["action_id"] = "another-owned-action"
    else:
        cursor = cursor.split(":")[0] + ":9999999999"
    with pytest.raises(ToolValidationError, match="cursor does not match"):
        await _run_history_fetch(
            action_agent,
            step_id="next-page",
            tool_def=HISTORY_FETCH_TOOL,
            args={"refs": ["S-1-THINK"], "cursor": cursor},
            state=state,
        )
