from __future__ import annotations

from pathlib import Path
from string import Formatter

import yaml

from pantaray_agents.agents.action_agent.runtime.handlers.tool_runtime import (
    PARALLEL_SAFE_TOOL_IDS,
    SOLO_TURN_TOOL_IDS,
)
from pantaray_llm.profiles.subagent_models import SUBAGENT_MODEL_SETTINGS


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _executing_config() -> dict[str, object]:
    config = yaml.safe_load(
        _read_text(
            Path(__file__).parents[3]
            / "src"
            / "pantaray_agents"
            / "prompts"
            / "action"
            / "executing.yaml"
        )
    )
    assert isinstance(config, dict)
    return config


def _executing_prompt_template() -> str:
    template = _executing_config().get("prompt")
    assert isinstance(template, str)
    return template


def _soft_plan_section() -> str:
    config = _executing_config()
    rules = config.get("tool_use_rules")
    assert isinstance(rules, dict)
    rule = rules.get("supervisor_soft_orchestration")
    assert isinstance(rule, str)
    return rule


def test_executing_prompt_defines_supervisor_final_answer_flow() -> None:
    text = _read_text(
        Path(__file__).parents[3]
        / "src"
        / "pantaray_agents"
        / "prompts"
        / "action"
        / "executing.yaml"
    )
    assert "<final_answer>" not in text
    assert "## Final Answer Flow" in text
    assert "Pending Final Answer Draft" in text
    assert "call `draft_final_answer` first" in text
    assert "call `submit_final_answer`" in text
    assert "Do not restate its internal details in the final answer" in text


def test_executing_prompt_defines_one_parent_tool_use_rule() -> None:
    text = _read_text(
        Path(__file__).parents[3]
        / "src"
        / "pantaray_agents"
        / "prompts"
        / "action"
        / "executing.yaml"
    )
    assert "## Supervisor Mode Rules" not in text
    assert "## Tool Use Rules" in text
    assert "{tool_use_rules}" in text
    assert "tool_use_rules:" in text
    assert "supervisor_soft_orchestration:" in text
    # 親プロンプトは Goal Worker 協調セクションを持たない。
    assert "supervisor_goal_worker:" not in text
    assert "{goal_conversations}" not in text
    assert "{pending_goal_completion_evidence}" not in text


def test_executing_prompt_keeps_one_optional_complex_task_plan() -> None:
    section = _soft_plan_section()

    assert "For a complex task, you may use one `plan.md`" in section
    assert "Do not create it for a small task" in section
    assert "same `plan.md`" in section
    assert all(
        required_part in section
        for required_part in (
            "Explicit user requests",
            "inferred true purpose, clearly labeled as an inference",
            "Success criteria",
            "Constraints and non-goals",
        )
    )
    assert "does not select an Action mode" in section
    assert "not a mandatory checklist" in section
    assert "open items neither block finalization nor prove success" in section


def test_executing_prompt_reconciles_plan_and_reports_against_current_evidence() -> (
    None
):
    section = _soft_plan_section()

    evidence_inputs = (
        "latest user instructions",
        "existing `plan.md`",
        "subagent reports",
        "actual tool results and current DB/file state",
    )
    assert all(input_name in section for input_name in evidence_inputs)
    assert "latest user instructions and verified evidence take precedence" in section
    assert "Update a stale `plan.md`" in section
    assert "evidence candidates, not truth" in section
    assert "instead of accepting them blindly" in section
    assert "inspect the resulting current state" in section
    assert "mutation tool's success" in section
    assert "purely inline answer" in section
    assert "call `history_fetch`" in section


def test_executing_prompt_delegates_model_guidance_to_spawn_tool_metadata() -> None:
    section = _soft_plan_section()
    prompt_text = _read_text(
        Path(__file__).parents[3]
        / "src"
        / "pantaray_agents"
        / "prompts"
        / "action"
        / "executing.yaml"
    )

    assert "Use subagents only when independent delegation adds clear value" in section
    assert "choose an explicit model from the tool definition" in section
    for setting in SUBAGENT_MODEL_SETTINGS:
        assert setting.selector not in prompt_text
        assert setting.recommendation not in prompt_text


def test_executing_prompt_states_the_tool_batch_rules() -> None:
    """1 ターン複数呼び出しの可否を、実行時のポリシーと同じ語で宣言している。"""

    text = _read_text(
        Path(__file__).parents[3]
        / "src"
        / "pantaray_agents"
        / "prompts"
        / "action"
        / "executing.yaml"
    )

    assert "exactly one provided tool" not in text
    assert "One turn may request several read-only calls at once" in text
    for tool_id in sorted(PARALLEL_SAFE_TOOL_IDS):
        assert f"`{tool_id}`" in text
    for tool_id in sorted(SOLO_TURN_TOOL_IDS):
        assert f"`{tool_id}`" in text
    assert "must be the only call of their turn" in text
    assert "Do not request two changing tools" in text
    assert "The runtime may defer or drop requested calls" in text
    assert "Every call needs its own internal `step_note`" in text


def test_action_prompts_include_memory_source_coverage_placeholder() -> None:
    base = Path(__file__).parents[3] / "src" / "pantaray_agents" / "prompts" / "action"
    text = _read_text(base / "executing.yaml")

    assert "{memory_source_coverage}" in text


def test_action_prompts_treat_request_summary_as_handoff_note() -> None:
    base = Path(__file__).parents[3] / "src" / "pantaray_agents" / "prompts" / "action"
    text = _read_text(base / "executing.yaml")

    assert "Suggestion Summary as the" in text
    assert "handoff note" in text
    assert "work surface" in text


# Rebuilt on every THINK, so they must sit behind the append-only history body
# for the prefix to stay byte-stable and hit the provider prompt cache. Every
# THINK appends its own copy, so nothing large belongs here.
# - supervisor_pending_final_answer: replaced by draft_final_answer / link_memory.
# - current_time: wall clock.
_TURN_TAIL_PROMPT_FIELDS = frozenset(
    {
        "supervisor_pending_final_answer",
        "current_time",
    }
)
# On ordinary turns, action_history grows at the end of the cacheable prefix.
# linkable_persisted_memory and memory_source_coverage are the snapshots taken at
# init; memory found mid-run reaches the model as its tool result.
_PREFIX_PROMPT_FIELDS = frozenset(
    {
        "workspace_path_contract",
        "workspace_context_rules",
        "workspace_context_prompt",
        "agents_md_instructions",
        "user_request",
        "request_summary",
        "target_context",
        "memory_context_model",
        "insight_data",
        "structured_fact_data",
        "memory_artifact_references",
        "linkable_persisted_memory",
        "memory_source_coverage",
        "action_history",
    }
)


def _prompt_fields(template: str) -> set[str]:
    return {
        field for _, field, _, _ in Formatter().parse(template) if field is not None
    }


def _render(template: str, *, turn: str) -> str:
    values = {field: f"<{field}>" for field in _PREFIX_PROMPT_FIELDS}
    values.update({field: f"<{field} {turn}>" for field in _TURN_TAIL_PROMPT_FIELDS})
    return template.format(**values)


def test_every_executing_prompt_field_is_classified_as_prefix_or_turn_tail() -> None:
    """新しい差し込み値は、キャッシュ規約のどちら側かを宣言してから足す。"""

    assert _prompt_fields(_executing_prompt_template()) == (
        _PREFIX_PROMPT_FIELDS | _TURN_TAIL_PROMPT_FIELDS
    )


def test_each_section_sits_on_its_side_of_action_history() -> None:
    template = _executing_prompt_template()
    boundary = template.index("{action_history}")

    for field in sorted(_PREFIX_PROMPT_FIELDS - {"action_history"}):
        assert template.index("{" + field + "}") < boundary
    for field in sorted(_TURN_TAIL_PROMPT_FIELDS):
        assert template.index("{" + field + "}") > boundary


def test_prompt_prefix_is_byte_identical_when_only_the_turn_tail_changes() -> None:
    """同じ履歴なら、時刻などが変わってもプレフィックスはバイト一致する。"""

    template = _executing_prompt_template()
    first = _render(template, turn="turn-1")
    second = _render(template, turn="turn-2")

    split = first.index("<action_history>") + len("<action_history>")
    assert first[:split].encode("utf-8") == second[:split].encode("utf-8")
    assert "## Action History" in first[:split]
    assert first[split:] != second[split:]
    for field in sorted(_TURN_TAIL_PROMPT_FIELDS):
        assert f"<{field} turn-1>" in first[split:]
