"""Cached LangGraph topology for ActionAgent."""

from __future__ import annotations

from collections.abc import Hashable, Mapping
from functools import lru_cache
from typing import Final, Literal, Protocol, TypeGuard, cast

from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, StateGraph
from langgraph.graph.state import CompiledStateGraph

from pantaray_agents.agents.action_agent.runtime.state import ActionAgentState

type ResumeRouteName = Literal[
    "init",
    "think",
    "action",
    "finalize",
    "halt",
]

ACTION_GRAPH_RUNTIME_CONFIG_KEY: Final = "action_graph_runtime"

RESUME_ROUTE_TO_NODE: Final[dict[ResumeRouteName, str]] = {
    "init": "init",
    "think": "think",
    "action": "action",
    "finalize": "finalize",
    "halt": END,
}

_REQUIRED_RUNTIME_METHODS: Final[tuple[str, ...]] = (
    "resume_gate",
    "init",
    "think",
    "action",
    "finalize",
    "route_from_resume",
    "route_from_think",
    "route_after_action",
)
_REQUIRED_RUNTIME_DATA_ATTRIBUTES: Final[tuple[str, ...]] = (
    "request",
    "state_config",
    "emit_action_step",
    "emit_error",
    "services",
)


class ActionGraphRuntimeLike(Protocol):
    request: object
    state_config: object
    emit_action_step: object
    emit_error: object
    services: object

    async def resume_gate(self, state: ActionAgentState) -> ActionAgentState: ...

    async def init(self, state: ActionAgentState) -> ActionAgentState: ...

    async def think(self, state: ActionAgentState) -> ActionAgentState: ...

    async def action(self, state: ActionAgentState) -> ActionAgentState: ...

    async def finalize(self, state: ActionAgentState) -> ActionAgentState: ...

    def route_from_resume(self, state: ActionAgentState) -> str: ...

    def route_from_think(self, state: ActionAgentState) -> str: ...

    def route_after_action(self, state: ActionAgentState) -> str: ...


def _is_action_graph_runtime_like(value: object) -> TypeGuard[ActionGraphRuntimeLike]:
    for attr_name in _REQUIRED_RUNTIME_DATA_ATTRIBUTES:
        if not hasattr(value, attr_name):
            return False
    for method_name in _REQUIRED_RUNTIME_METHODS:
        if not callable(getattr(value, method_name, None)):
            return False
    return True


def runtime_from_config(config: RunnableConfig) -> ActionGraphRuntimeLike:
    if not isinstance(config, Mapping):
        raise RuntimeError("Action graph runtime config is missing.")
    configurable = config.get("configurable")
    if not isinstance(configurable, Mapping):
        raise RuntimeError("Action graph runtime config is missing.")
    runtime = configurable.get(ACTION_GRAPH_RUNTIME_CONFIG_KEY)
    if not _is_action_graph_runtime_like(runtime):
        raise RuntimeError(
            "Action graph runtime must provide the ActionGraphRuntime interface."
        )
    return runtime


async def resume_gate_node(
    state: ActionAgentState,
    config: RunnableConfig,
) -> ActionAgentState:
    return await runtime_from_config(config).resume_gate(state)


async def init_node(
    state: ActionAgentState,
    config: RunnableConfig,
) -> ActionAgentState:
    return await runtime_from_config(config).init(state)


async def think_node(
    state: ActionAgentState,
    config: RunnableConfig,
) -> ActionAgentState:
    return await runtime_from_config(config).think(state)


async def action_node(
    state: ActionAgentState,
    config: RunnableConfig,
) -> ActionAgentState:
    return await runtime_from_config(config).action(state)


async def finalize_node(
    state: ActionAgentState,
    config: RunnableConfig,
) -> ActionAgentState:
    return await runtime_from_config(config).finalize(state)


def route_from_resume_node(
    state: ActionAgentState,
    config: RunnableConfig,
) -> str:
    return runtime_from_config(config).route_from_resume(state)


def route_from_think_node(
    state: ActionAgentState,
    config: RunnableConfig,
) -> str:
    return runtime_from_config(config).route_from_think(state)


def route_after_action_node(
    state: ActionAgentState,
    config: RunnableConfig,
) -> str:
    return runtime_from_config(config).route_after_action(state)


@lru_cache(maxsize=1)
def cached_action_agent_compiled_graph() -> CompiledStateGraph:
    graph = StateGraph(ActionAgentState)
    graph.add_node("resume_gate", resume_gate_node)
    graph.add_node("init", init_node)
    graph.add_node("think", think_node)
    graph.add_node("action", action_node)
    graph.add_node("finalize", finalize_node)

    graph.set_entry_point("resume_gate")
    graph.add_conditional_edges(
        "resume_gate",
        route_from_resume_node,
        cast(dict[Hashable, str], RESUME_ROUTE_TO_NODE),
    )
    graph.add_edge("init", "think")
    graph.add_conditional_edges(
        "think",
        route_from_think_node,
        {
            "think": "think",
            "action": "action",
            "finalize": "finalize",
        },
    )
    graph.add_conditional_edges(
        "action",
        route_after_action_node,
        {
            "halt": END,
            "think": "think",
            "finalize": "finalize",
        },
    )
    graph.add_edge("finalize", END)

    return graph.compile(checkpointer=None)


def clear_cached_action_agent_graph() -> None:
    cached_action_agent_compiled_graph.cache_clear()
