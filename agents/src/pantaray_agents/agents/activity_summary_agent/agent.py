"""ActivitySummaryAgent - 階層的なサマリ（1h/24h/1w/1m/3m）を生成する"""

import logging
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import TypedDict

from pantaray_agents.agents.core import BaseAgent, CountingSink
from pantaray_agents.repositories.runtime_ports import ActivityRepositoryPort
from pantaray_agents.schema.agent.activity import (
    ActivitySummaryAgentRequest,
    ActivitySummaryAgentResponse,
)
from pantaray_agents.schema.agent.base import (
    AgentError,
    AgentRequest,
    JSONValue,
    StatusType,
)
from pantaray_agents.schema.repositories.repository import DBRow
from pantaray_agents.schema.repository_errors import (
    is_retryable_repository_exception,
)
from pantaray_agents.utils.local_time import (
    describe_utc_timestamp,
    local_period,
    local_time_note,
    local_zone_name,
)
from pantaray_agents.utils.prompt_loader import PromptConfig
from pantaray_agents.utils.trace_context import TraceContextManager
from pantaray_llm.profiles import ACTIVITY_SUMMARY_PROFILE_ID

logger = logging.getLogger(__name__)

type ActivitySummaryConfig = dict[str, JSONValue]


class ActivitySummaryContextData(TypedDict):
    """ActivitySummaryAgent のコンテキストデータ型"""

    user_id: str
    summary_id: str
    summary_type: str
    period_start: str
    period_end: str
    source_data: list[DBRow]
    source_ids: list[str]
    source_data_formatted: str
    source_count: int
    workspace_context_prompt: str


class ActivitySummaryExtractedData(TypedDict):
    """LLMレスポンスから抽出されたデータ型"""

    thinking: str | None
    summary: str


class ActivitySummaryErrorParams(TypedDict, total=False):
    """エラーレスポンス用パラメータ型"""

    summary_id: str
    user_id: str
    summary_type: str
    period_start: str
    period_end: str


# データがない場合の定型メッセージテンプレート
NO_ACTIVITY_TEMPLATE = """# {summary_type} Summary ({period_start} - {period_end})

## Overview
No activity was recorded during this period.

## Notes
- No screen captures or lower-level summaries were available, so a summary could not be generated."""


def _local_period(context: ActivitySummaryContextData) -> dict[str, str]:
    """The period as the model reads it; the response keeps the UTC period."""

    return {
        "period_start": describe_utc_timestamp(context["period_start"]),
        "period_end": describe_utc_timestamp(context["period_end"]),
    }


# リクエスト（= asyncio Task）単位で扱う状態
#
# NOTE:
# - ActivitySummary の状態遷移と永続化は local runtime / queue が SSOT として担う。
# - agent は同一リクエスト内の source_data/source_ids を安全に再利用するために
#   ContextVar を使い、インスタンス状態（並行実行で混線する）に依存しない。
_ACTIVITY_SUMMARY_CONTEXT: ContextVar[ActivitySummaryContextData | None] = ContextVar(
    "activity_summary_context",
    default=None,
)
_ACTIVITY_SUMMARY_SOURCE_IDS: ContextVar[tuple[str, ...] | None] = ContextVar(
    "activity_summary_source_ids",
    default=None,
)


def _clear_activity_summary_request_state() -> None:
    """ActivitySummaryAgent のリクエストスコープ状態をクリアする。"""
    _ACTIVITY_SUMMARY_CONTEXT.set(None)
    _ACTIVITY_SUMMARY_SOURCE_IDS.set(None)


class ActivitySummaryAgent(BaseAgent[ActivitySummaryAgentResponse]):
    """階層的なサマリ（1h/24h/1w/1m/3m）を生成するエージェント"""

    LLM_INFERENCE_PROFILE_ID = ACTIVITY_SUMMARY_PROFILE_ID
    # バリアントキー（A/Bテスト対応）
    #
    # NOTE:
    # - `prompt_name` / `prompt_version` は DB 永続化および下位サマリ選択のキーとして扱う。
    # - まずは固定値で運用し、A/B 時は prompt_version などを切り替える想定。
    PROMPT_NAME = "activity_summary"
    PROMPT_VERSION = "1.0"

    def __init__(
        self,
        config: ActivitySummaryConfig,
        repository: ActivityRepositoryPort | None = None,
    ):
        """エージェントを初期化する。

        Args:
            config: エージェント設定
            repository: Activity用リポジトリ
        """
        super().__init__(config)
        if repository is None:
            raise ValueError("ActivitySummaryAgent には repository が必須です")
        self.repository = repository

        # プロンプト設定のロード（system_instruction と prompt を分離）
        self._prompt_config: PromptConfig = self._load_prompt_config("activity_summary")
        self._last_prompt_text = ""

    @property
    def prompt(self) -> str:
        """後方互換性のためのプロパティ（prompt部分のみ返す）"""
        return self._prompt_config.prompt

    @property
    def system_instruction(self) -> str | None:
        """system_instruction を返す"""
        return self._prompt_config.system_instruction

    @property
    def last_prompt_text(self) -> str:
        return self._last_prompt_text

    async def run_without_persistence(
        self,
        request: AgentRequest,
    ) -> ActivitySummaryAgentResponse:
        return await self._run_generation(request)

    async def process(self, request: AgentRequest) -> ActivitySummaryAgentResponse:
        """生成のみを実行する。

        ActivitySummary の状態遷移と永続化は local runtime / queue が SSOT として担う。
        agent はリクエストからレスポンスを生成する責務に限定する。
        """
        return await self.run_without_persistence(request)

    async def _run_generation(
        self,
        request: AgentRequest,
    ) -> ActivitySummaryAgentResponse:
        validated_request = await self._validate_request(request)
        if not isinstance(validated_request, ActivitySummaryAgentRequest):
            raise TypeError("Request must be of type ActivitySummaryAgentRequest")

        _clear_activity_summary_request_state()
        self._last_prompt_text = ""
        try:
            with TraceContextManager(
                user_id=str(validated_request.user_id),
                request_id=(
                    str(validated_request.request_id)
                    if isinstance(getattr(validated_request, "request_id", None), str)
                    else None
                ),
                extra={"activity_summary_id": str(validated_request.summary_id)},
            ):
                self._current_language = getattr(validated_request, "language", None)
                try:
                    context_data = await self._fetch_context_data(validated_request)
                except Exception as exc:  # noqa: BLE001
                    if is_retryable_repository_exception(exc):
                        raise
                    response = await self._handle_fetch_context_error(
                        exc, validated_request, self._get_id_attrs()
                    )
                    if not isinstance(response, ActivitySummaryAgentResponse):
                        raise TypeError(
                            "ActivitySummaryAgent must return ActivitySummaryAgentResponse"
                        ) from exc
                    return response

                if context_data["source_count"] == 0:
                    return ActivitySummaryAgentResponse(
                        summary_id=context_data["summary_id"],
                        user_id=context_data["user_id"],
                        summary_type=context_data["summary_type"],
                        summary=NO_ACTIVITY_TEMPLATE.format(
                            summary_type=context_data["summary_type"],
                            **_local_period(context_data),
                        ),
                        thinking=None,
                        period_start=context_data["period_start"],
                        period_end=context_data["period_end"],
                        source_ids=[],
                        created_at=datetime.now(UTC).isoformat(),
                        status=StatusType.SUCCESS,
                        error=None,
                    )

                try:
                    prompt = self._build_prompt(context_data)
                    extracted = await self._process_llm_response(prompt)
                    response = self._create_success_response(
                        validated_request,
                        extracted,
                    )
                    if not isinstance(response, ActivitySummaryAgentResponse):
                        raise TypeError(
                            "ActivitySummaryAgent must return ActivitySummaryAgentResponse"
                        )
                    return response
                except (ValueError, TypeError) as exc:
                    response = await self._handle_validation_error(
                        exc, validated_request, self._get_id_attrs()
                    )
                except (ConnectionError, TimeoutError) as exc:
                    response = await self._handle_connection_error(
                        exc, validated_request, self._get_id_attrs()
                    )
                except (RuntimeError, OSError, AttributeError) as exc:
                    response = await self._handle_system_error(
                        exc, validated_request, self._get_id_attrs()
                    )
                except Exception as exc:
                    response = await self._handle_general_error(
                        exc, validated_request, self._get_id_attrs()
                    )

                if not isinstance(response, ActivitySummaryAgentResponse):
                    raise TypeError(
                        "ActivitySummaryAgent must return ActivitySummaryAgentResponse"
                    )
                return response
        finally:
            _clear_activity_summary_request_state()

    def get_response_class(self) -> type[ActivitySummaryAgentResponse]:
        """レスポンスクラスを返す"""
        return ActivitySummaryAgentResponse

    def get_error_code_prefix(self) -> str:
        """エラーコードの接頭辞を返す"""
        return "ACTIVITY_SUMMARY"

    async def _validate_request(
        self, request: AgentRequest
    ) -> ActivitySummaryAgentRequest:
        """リクエストの検証と型変換を行う"""
        if not isinstance(request, ActivitySummaryAgentRequest):
            if hasattr(request, "model_dump"):
                return ActivitySummaryAgentRequest(**request.model_dump())
            raise TypeError("Request must be of type ActivitySummaryAgentRequest")
        return request

    async def _fetch_context_data(
        self, request: AgentRequest
    ) -> ActivitySummaryContextData:
        """コンテキストデータを取得する"""
        if not isinstance(request, ActivitySummaryAgentRequest):
            raise TypeError("Request must be of type ActivitySummaryAgentRequest")
        summary_request = request

        # 同一リクエスト内で source_data/source_ids を再利用する。
        cached = _ACTIVITY_SUMMARY_CONTEXT.get()
        if cached is not None:
            if (
                cached.get("user_id") == summary_request.user_id
                and cached.get("summary_id") == summary_request.summary_id
                and cached.get("summary_type") == summary_request.summary_type
                and cached.get("period_start") == summary_request.period_start
                and cached.get("period_end") == summary_request.period_end
            ):
                return cached

        # ソースデータを取得
        source_result = await self.repository.get_source_data_for_summary(
            user_id=summary_request.user_id,
            summary_type=summary_request.summary_type,
            period_start=summary_request.period_start,
            period_end=summary_request.period_end,
            prompt_name=self.PROMPT_NAME,
            prompt_version=self.PROMPT_VERSION,
        )

        source_data: list[DBRow] = source_result.data if source_result.data else []
        source_ids: list[str] = []

        # ソースデータをLLM入力向けに整形
        formatted_sources: list[str] = []
        for i, item in enumerate(source_data):
            # 1h サマリの場合は activity_logs、それ以外は activity_summaries
            if summary_request.summary_type == "1h":
                prefix = "AL"
                item_id = str(item.get("log_id", ""))
                content = str(item.get("description", ""))
            else:
                prefix = "AS"
                item_id = str(item.get("summary_id", ""))
                content = str(item.get("summary", ""))
            period = local_period(str(item["period_start"]), str(item["period_end"]))

            source_ids.append(item_id)
            formatted_sources.append(
                f"Source {i + 1} ({prefix}) Period: {period}\n{content}\n"
            )

        context = ActivitySummaryContextData(
            user_id=summary_request.user_id,
            summary_id=summary_request.summary_id,
            summary_type=summary_request.summary_type,
            period_start=summary_request.period_start,
            period_end=summary_request.period_end,
            source_data=source_data,
            source_ids=source_ids,
            source_data_formatted="\n---\n".join(formatted_sources)
            if formatted_sources
            else "No source data available.",
            source_count=len(source_data),
            workspace_context_prompt=summary_request.workspace_context_prompt or "",
        )
        # リクエストスコープに保存（並行実行でも混線しない）
        _ACTIVITY_SUMMARY_CONTEXT.set(context)
        _ACTIVITY_SUMMARY_SOURCE_IDS.set(tuple(source_ids))
        return context

    def _build_prompt(self, context_data: ActivitySummaryContextData) -> str:
        """プロンプトを構築する"""
        return self.prompt.format(
            summary_type=context_data["summary_type"],
            **_local_period(context_data),
            local_time_note=local_time_note(local_zone_name()),
            source_data=context_data["source_data_formatted"],
            workspace_context_prompt=context_data["workspace_context_prompt"],
        )

    async def _process_llm_response(self, prompt: str) -> ActivitySummaryExtractedData:
        """LLMレスポンスを処理する（画像は使用しない）。

        出力仕様:
            ActivitySummaryAgent は「本文のみ」を採用する。
            `<thinking>` / `<answer>` などのタグは出力仕様として前提にせず、
            混入しても抽出/除去は行わない（LLM出力全体を本文として扱う）。
        """
        # YAML から読み込んだ system_instruction に言語プレフィックスを合成
        base_instruction = (
            self.system_instruction
            or f"{self.DEFAULT_SYSTEM_INSTRUCTION} Summarize user activities concisely and comprehensively."
        )
        use_system_instruction = self._compose_system_instruction(
            base_instruction=base_instruction,
            language=getattr(self, "_current_language", None),
        )
        self._last_prompt_text = prompt
        llm_response_text = await self._generate_llm_response(
            prompt=prompt,
            sink=CountingSink(),
            system_instruction=use_system_instruction,
        )
        thinking = self._consume_llm_thoughts()

        # 仕様: 本文のみ（タグ処理は行わず、LLMの出力全体をそのまま本文として扱う）
        summary = (llm_response_text or "").strip()

        return ActivitySummaryExtractedData(
            thinking=thinking,
            summary=summary,
        )

    def _create_success_response(
        self, request: AgentRequest, extracted_data: ActivitySummaryExtractedData
    ) -> ActivitySummaryAgentResponse:
        """成功レスポンスを作成する"""
        if not isinstance(request, ActivitySummaryAgentRequest):
            raise TypeError("Request must be of type ActivitySummaryAgentRequest")
        summary_request = request

        # リクエストスコープからソースIDを取得（並行実行でも混線しない）
        source_ids_tuple = _ACTIVITY_SUMMARY_SOURCE_IDS.get()
        source_ids = list(source_ids_tuple) if source_ids_tuple else []

        return ActivitySummaryAgentResponse(
            summary_id=summary_request.summary_id,
            user_id=summary_request.user_id,
            summary_type=summary_request.summary_type,
            summary=extracted_data["summary"],
            thinking=extracted_data["thinking"],
            period_start=summary_request.period_start,
            period_end=summary_request.period_end,
            source_ids=source_ids,
            created_at=datetime.now(UTC).isoformat(),
            status=StatusType.SUCCESS,
            error=None,
        )

    async def _save_response(self, response: ActivitySummaryAgentResponse) -> None:
        del response
        raise NotImplementedError(
            "ActivitySummaryAgent persistence is owned by orchestration/runtime"
        )

    def _get_id_attrs(self) -> dict[str, str]:
        """ID属性名とレスポンスパラメータ名の辞書を返す"""
        return {
            "summary_id": "summary_id",
            "user_id": "user_id",
        }

    async def _handle_agent_error(
        self, error: AgentError, response_params: ActivitySummaryErrorParams
    ) -> ActivitySummaryAgentResponse:
        """エラーを処理し、レスポンスを返す"""
        summary_id = response_params.get("summary_id", "error_id")
        user_id = response_params.get("user_id")
        if not isinstance(user_id, str) or not user_id:
            raise ValueError("user_id はエラー処理に必須です")

        error_response = self._create_error_response(
            error,
            {
                "summary_id": summary_id,
                "user_id": user_id,
                "summary_type": response_params.get("summary_type", ""),
                "summary": "",
                "thinking": None,
                "period_start": response_params.get("period_start", ""),
                "period_end": response_params.get("period_end", ""),
                "source_ids": [],
            },
        )

        return error_response
