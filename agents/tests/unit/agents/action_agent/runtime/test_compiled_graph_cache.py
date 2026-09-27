from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from unittest.mock import MagicMock

import pytest

from pantaray_agents.agents.action_agent.runtime.compiled_graph import (
    ACTION_GRAPH_RUNTIME_CONFIG_KEY,
    cached_action_agent_compiled_graph,
    clear_cached_action_agent_graph,
    runtime_from_config,
)
from pantaray_agents.agents.action_agent.runtime.graph import build_action_agent_graph
from pantaray_agents.agents.action_agent.runtime.state import ActionAgentState


@pytest.fixture(autouse=True)
def clear_graph_cache() -> None:
    clear_cached_action_agent_graph()
    yield
    clear_cached_action_agent_graph()


@dataclass
class _FakeRuntime:
    label: str
    state_config: dict[str, int]
    resume_route: str = "init"
    call_events: list[str] = field(default_factory=list)
    request: object = field(default_factory=MagicMock)
    emit_action_step: object = field(default_factory=MagicMock)
    emit_error: object = field(default_factory=MagicMock)
    services: object = field(default_factory=MagicMock)

    async def resume_gate(self, state: ActionAgentState) -> ActionAgentState:
        return state

    async def init(self, state: ActionAgentState) -> ActionAgentState:
        self.call_events.append(f"{self.label}:init")
        state["phase"] = "planning"
        return state

    async def think(self, state: ActionAgentState) -> ActionAgentState:
        phase = state["phase"]
        if phase == "planning":
            self.call_events.append(f"{self.label}:think=planning")
        else:
            self.call_events.append(
                f"{self.label}:think=executing:cap={self.state_config['max_parallel_memory_queries']}"
            )
        return state

    async def action(self, state: ActionAgentState) -> ActionAgentState:
        self.call_events.append(f"{self.label}:action")
        state["phase"] = "executing"
        return state

    async def finalize(self, state: ActionAgentState) -> ActionAgentState:
        self.call_events.append(f"{self.label}:finalize")
        return state

    def route_from_resume(self, _state: ActionAgentState) -> str:
        self.call_events.append(f"{self.label}:route_resume")
        return self.resume_route

    def route_from_think(self, state: ActionAgentState) -> str:
        phase = state["phase"]
        self.call_events.append(f"{self.label}:route_think={phase}")
        return "action" if phase == "planning" else "finalize"

    def route_after_action(self, _state: ActionAgentState) -> str:
        self.call_events.append(f"{self.label}:route_action")
        return "think"


def _state() -> ActionAgentState:
    return {
        "max_steps": 3,
        "max_tool_steps": 3,
        "step": 0,
        "tool_steps_taken": 0,
        "llm_steps_taken": 0,
    }


def test_runtime_from_config_reports_missing_runtime() -> None:
    with pytest.raises(RuntimeError, match="Action graph runtime config is missing"):
        runtime_from_config({})


def test_build_action_agent_graph_reuses_cached_compile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from pantaray_agents.agents.action_agent.runtime import compiled_graph

    original_compile = compiled_graph.StateGraph.compile
    compile_count = 0

    def _counting_compile(self: object, *args: object, **kwargs: object) -> object:
        nonlocal compile_count
        compile_count += 1
        return original_compile(self, *args, **kwargs)

    monkeypatch.setattr(compiled_graph.StateGraph, "compile", _counting_compile)

    build_action_agent_graph(_FakeRuntime("A", {"max_parallel_memory_queries": 1}))
    build_action_agent_graph(_FakeRuntime("B", {"max_parallel_memory_queries": 2}))

    assert compile_count == 1


def test_compiled_graph_contains_parent_nodes_only() -> None:
    assert set(cached_action_agent_compiled_graph().nodes) == {
        "__start__",
        "resume_gate",
        "init",
        "think",
        "action",
        "finalize",
    }


@pytest.mark.asyncio
async def test_cached_graph_keeps_parallel_runtime_configs_isolated() -> None:
    runtime_a = _FakeRuntime(
        "A",
        {"max_parallel_memory_queries": 1},
    )
    runtime_b = _FakeRuntime(
        "B",
        {"max_parallel_memory_queries": 9},
    )
    runner_a = build_action_agent_graph(runtime_a)  # type: ignore[arg-type]
    runner_b = build_action_agent_graph(runtime_b)  # type: ignore[arg-type]

    await asyncio.gather(runner_a(_state()), runner_b(_state()))

    assert runtime_a.call_events == [
        "A:route_resume",
        "A:init",
        "A:think=planning",
        "A:route_think=planning",
        "A:action",
        "A:route_action",
        "A:think=executing:cap=1",
        "A:route_think=executing",
        "A:finalize",
    ]
    assert runtime_b.call_events == [
        "B:route_resume",
        "B:init",
        "B:think=planning",
        "B:route_think=planning",
        "B:action",
        "B:route_action",
        "B:think=executing:cap=9",
        "B:route_think=executing",
        "B:finalize",
    ]


@pytest.mark.asyncio
async def test_halt_resume_route_ends_without_running_any_agent_node() -> None:
    runtime = _FakeRuntime(
        "paused",
        {"max_parallel_memory_queries": 1},
        resume_route="halt",
    )
    runner = build_action_agent_graph(runtime)  # type: ignore[arg-type]

    await runner(_state())

    assert runtime.call_events == ["paused:route_resume"]


def test_build_action_agent_graph_passes_runtime_in_invoke_config() -> None:
    runtime = _FakeRuntime("A", {"max_parallel_memory_queries": 1})

    captured_config: dict[str, object] = {}

    class _CompiledGraph:
        async def ainvoke(
            self,
            _state: object,
            *,
            config: dict[str, object],
        ) -> ActionAgentState:
            captured_config.update(config)
            return _state  # type: ignore[return-value]

    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(
            "pantaray_agents.agents.action_agent.runtime.graph.cached_action_agent_compiled_graph",
            lambda: _CompiledGraph(),
        )
        runner = build_action_agent_graph(runtime)  # type: ignore[arg-type]
        asyncio.run(runner(_state()))

    assert captured_config["recursion_limit"] == 22
    configurable = captured_config["configurable"]
    assert isinstance(configurable, dict)
    assert configurable[ACTION_GRAPH_RUNTIME_CONFIG_KEY] is runtime
