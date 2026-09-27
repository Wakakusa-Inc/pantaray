import logging
from collections.abc import AsyncIterator, Awaitable
from functools import lru_cache
from typing import Protocol

from pantaray_agents.agents import (
    ActionAgent,
    SuggestionAgent,
)
from pantaray_agents.application.action.ports import ActionUseCase
from pantaray_agents.application.action.use_case_service import (
    ActionUseCaseDeps,
    ActionUseCaseService,
)
from pantaray_agents.config_shared import AppConfig, ConfigValue
from pantaray_agents.local_runtime.agent_state import (
    LocalActionRepository,
    LocalSuggestionRepository,
)
from pantaray_agents.local_runtime.llm_proxy import build_local_llm_proxy_client
from pantaray_agents.local_runtime.runtime.activity_local_repository import (
    SQLiteActivityRuntimeRepository,
)
from pantaray_agents.local_runtime.runtime.bootstrap import (
    read_local_runtime_db_config,
)
from pantaray_agents.local_runtime.suggestion_state.repository import (
    LocalSuggestionStateRepository,
)
from pantaray_agents.local_runtime.tooling.suggestion_research import (
    InsightActivityStart,
    LocalSuggestionResearchTools,
    SuggestionResearchSnapshot,
)
from pantaray_agents.local_runtime.user_settings_repository import (
    LocalUserSettingsRepository,
)
from pantaray_agents.mock.mock_client_factory import (
    create_mock_action_repository,
    create_mock_client,
    create_mock_suggestion_repository,
)
from pantaray_agents.mock.mock_llm_client import MockLLMClient
from pantaray_agents.mock.mock_user_settings_repository import (
    MockUserSettingsRepository,
)
from pantaray_agents.mock.suggestion_research import (
    build_mock_suggestion_research_tools,
)
from pantaray_agents.repositories.runtime_ports import (
    ActionRepositoryPort,
    SuggestionRepositoryPort,
)
from pantaray_agents.repositories.user_settings_port import UserSettingsRepositoryPort
from pantaray_agents.settings_loader import load_active_settings

logger = logging.getLogger(__name__)


def _get_current_settings() -> AppConfig:
    return load_active_settings()


def _settings_get(key: str, default: ConfigValue | None = None) -> ConfigValue | None:
    """現在の設定から値を取得する（テストのpatchに追従する）。

    `dependencies.py` はテストで import 順序の影響を受けやすいため、設定は都度参照する。
    """
    st = _get_current_settings()
    return st.get(key, default)


def is_mock_mode() -> bool:
    """Return True if mock mode is enabled; prefer module-level settings (patched in tests)."""
    try:
        # Always prefer the live config.settings (tests patch this)
        return bool(_settings_get("use_mocks", False))
    except (AttributeError, KeyError, TypeError):
        return False


class LLMTextResponse(Protocol):
    """LLM text generation response の最小インターフェース。"""

    text: str


class LLMStreamChunk(Protocol):
    """LLM stream chunk の最小インターフェース。"""

    text: str


class LLMModelsProtocol(Protocol):
    """`client.aio.models` の最小インターフェース。"""

    def generate_content(self, **kwargs: object) -> Awaitable[LLMTextResponse]: ...

    def generate_content_stream(
        self, **kwargs: object
    ) -> Awaitable[AsyncIterator[LLMStreamChunk]] | AsyncIterator[LLMStreamChunk]: ...


class LLMAioProtocol(Protocol):
    """`client.aio` の最小インターフェース。"""

    models: LLMModelsProtocol


class LLMClientProtocol(Protocol):
    """LLM クライアントの最小インターフェース。"""

    aio: LLMAioProtocol
    files: object


@lru_cache
def get_llm_client() -> LLMClientProtocol:
    """LLM クライアントを返す。

    - MOCK モード（`USE_MOCKS=true`）ではモッククライアントを返す。
    - それ以外（本番/開発の実行モード）では local runtime 用の cloud proxy client を返す。
    - 本番（`USE_MOCKS=false`）ではフォールバックしない。初期化に失敗した場合は
      例外を送出して明示的に失敗させる。

    Returns:
        LLMClientProtocol: LLMクライアントインスタンス
    """
    st = _get_current_settings()
    llm_cfg_raw = st.get("llm", {}) if isinstance(st, dict) else {}
    llm_cfg = llm_cfg_raw if isinstance(llm_cfg_raw, dict) else {}
    use_mocks = bool(st.get("use_mocks", False)) if isinstance(st, dict) else False

    if use_mocks:
        # Mock 実行モード: MockLLMClient を返す
        client = create_mock_client(config={"llm": llm_cfg})
        # プロトコル互換のために型を絞る
        if isinstance(client, MockLLMClient):
            return client
        # 型が異なる場合でも、aio 属性を持つ限りは許容する
        return client  # type: ignore[return-value]

    # 実行モード: local runtime 用 cloud proxy client を返す
    try:
        return build_local_llm_proxy_client()
    except Exception as e:  # noqa: BLE001
        # 本番ではフォールバックしない。原因を明示して例外送出。
        logger.critical(
            "LLM クライアント初期化に失敗しました（本番モードのためフォールバック無効）: %s",
            e,
            exc_info=True,
        )
        raise RuntimeError(
            "LLM クライアント初期化に失敗しました。USE_MOCKS=false 時は mock へフォールバックしません。"
        ) from e


def get_local_activity_repository() -> SQLiteActivityRuntimeRepository:
    db_path, busy_timeout_ms = read_local_runtime_db_config()
    return SQLiteActivityRuntimeRepository(
        db_path=db_path,
        busy_timeout_ms=busy_timeout_ms,
    )


async def get_suggestion_repository() -> SuggestionRepositoryPort:
    if is_mock_mode():
        return create_mock_suggestion_repository()
    db_path, busy_timeout_ms = read_local_runtime_db_config()
    return LocalSuggestionRepository(
        db_path=str(db_path),
        busy_timeout_ms=busy_timeout_ms,
        activity_repository=get_local_activity_repository(),
    )


def get_local_suggestion_state_repository() -> LocalSuggestionStateRepository:
    db_path, busy_timeout_ms = read_local_runtime_db_config()
    return LocalSuggestionStateRepository(
        db_path=db_path,
        busy_timeout_ms=busy_timeout_ms,
    )


def get_local_action_repository() -> LocalActionRepository:
    db_path, busy_timeout_ms = read_local_runtime_db_config()
    return LocalActionRepository(
        db_path=db_path,
        busy_timeout_ms=busy_timeout_ms,
    )


async def get_action_repository() -> ActionRepositoryPort:
    if is_mock_mode():
        return create_mock_action_repository()
    return get_local_action_repository()


async def get_user_settings_repository() -> UserSettingsRepositoryPort:
    """UserSettingsRepository を取得する。

    言語設定など、system_users のユーザー設定を扱う。
    """

    if is_mock_mode():
        # モックモード: in-memory 実装を返す（WS/HTTP のテストを外部依存なしで成立させる）
        return MockUserSettingsRepository()  # type: ignore[return-value]
    db_path, busy_timeout_ms = read_local_runtime_db_config()
    return LocalUserSettingsRepository(
        db_path=str(db_path),
        busy_timeout_ms=busy_timeout_ms,
    )


async def get_suggestion_agent(
    *,
    research_snapshot: SuggestionResearchSnapshot,
    activity_start: InsightActivityStart | None,
) -> SuggestionAgent:
    repo = await get_suggestion_repository()
    llm = get_llm_client()
    st = _get_current_settings()
    agent_config = {
        "mode": st.get("mode") if isinstance(st, dict) else None,
        "llm_client": llm,
        "llm": st.get("llm", {}) if isinstance(st, dict) else {},
    }
    if is_mock_mode():
        research_tools = build_mock_suggestion_research_tools()
    else:
        db_path, busy_timeout_ms = read_local_runtime_db_config()
        research_tools = LocalSuggestionResearchTools(
            db_path=db_path,
            busy_timeout_ms=busy_timeout_ms,
            snapshot=research_snapshot,
            activity_start=activity_start,
        )
    agent = SuggestionAgent(
        config=agent_config,
        repository=repo,
        research_tools=research_tools,
        stable_memory=research_snapshot.stable_memory,
    )
    return agent


async def _build_action_agent() -> ActionAgent:
    repo = await get_action_repository()
    llm = get_llm_client()
    st = _get_current_settings()
    agent_config = {
        "mode": st.get("mode") if isinstance(st, dict) else None,
        "llm_client": llm,
        "llm": st.get("llm", {}) if isinstance(st, dict) else {},
    }
    agent = ActionAgent(config=agent_config, repository=repo)
    return agent


async def get_action_application_service() -> ActionUseCase:
    agent = await _build_action_agent()
    return ActionUseCaseService(ActionUseCaseDeps(agent=agent))
