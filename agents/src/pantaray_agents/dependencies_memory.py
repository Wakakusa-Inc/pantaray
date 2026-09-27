"""Memory and Activity agent composition; shared runtime dependencies remain upstream."""

import pantaray_agents.dependencies as deps
from pantaray_agents.agents import InsightAgent
from pantaray_agents.agents.activity_summary_agent import ActivitySummaryAgent
from pantaray_agents.repositories.runtime_ports import ActivityRepositoryPort


async def get_insight_agent() -> InsightAgent:
    """Compose the short Insight agent; it persists through the runtime, not a repo."""
    return InsightAgent(
        client=deps.get_llm_client(),
        llm_config={},
    )


async def get_activity_repository() -> ActivityRepositoryPort:
    """Activity系エージェント用リポジトリを取得する。"""
    return deps.get_local_activity_repository()


async def get_activity_summary_agent() -> ActivitySummaryAgent:
    """ActivitySummaryAgentを取得する。"""
    repo = await get_activity_repository()
    llm = deps.get_llm_client()
    st = deps._get_current_settings()
    agent_config = {
        "llm_client": llm,
        "llm": st.get("llm", {}) if isinstance(st, dict) else {},
    }
    agent = ActivitySummaryAgent(config=agent_config, repository=repo)
    return agent
