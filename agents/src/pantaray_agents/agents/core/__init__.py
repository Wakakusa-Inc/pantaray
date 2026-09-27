"""エージェント共通基盤（BaseAgent/Mixin類）を提供するモジュール。"""

from pantaray_agents.schema.repository_errors import (
    AgentRepositoryError,
    FetchContextError,
    RepositoryStage,
    SaveResponseError,
    StorageCommitError,
)

from .base import BaseAgent
from .error_contract import (
    ERROR_SPEC_BY_PHASE,
    AgentErrorPhase,
    AgentErrorSpec,
    AgentPhaseError,
    build_agent_error,
)
from .errors import AgentDependencyConfigError, PublicAgentHTTPError
from .mixins.context_utils_mixin import ContextUtilsMixin
from .mixins.error_handling_mixin import ErrorHandlingMixin
from .mixins.llm_generation_mixin import LLMGenerationMixin
from .mixins.llm_usage import (
    CountingSink,
    LlmUsage,
    TokenBudgetExceeded,
    TokenSink,
)
from .tool_llm_runner import StructuredLlmResult, ToolLlmRunner


def __getattr__(name: str) -> object:
    if name == "ReactAgentBase":
        from pantaray_agents.agents.artifact_react.base import ReactAgentBase

        return ReactAgentBase
    raise AttributeError(name)


__all__ = [
    "AgentRepositoryError",
    "AgentErrorPhase",
    "AgentErrorSpec",
    "AgentPhaseError",
    "BaseAgent",
    "AgentDependencyConfigError",
    "ContextUtilsMixin",
    "CountingSink",
    "ERROR_SPEC_BY_PHASE",
    "ErrorHandlingMixin",
    "FetchContextError",
    "LLMGenerationMixin",
    "LlmUsage",
    "PublicAgentHTTPError",
    "RepositoryStage",
    "ReactAgentBase",
    "SaveResponseError",
    "StorageCommitError",
    "StructuredLlmResult",
    "TokenBudgetExceeded",
    "TokenSink",
    "ToolLlmRunner",
    "build_agent_error",
]
