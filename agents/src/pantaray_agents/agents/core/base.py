"""エージェントの基底クラス

本クラスは軽量な調停役として、以下の責務のみを持つ:
- 初期化（LLMクライアントDI/検証）
- プロセス制御（validate/fetch/build/select/generate/save）
- サブクラスに要求される抽象メソッドの宣言

LLM呼び出し、エラーハンドリング、文脈処理は各ミックスインへ委譲する。
"""

import logging
import sqlite3
from abc import ABC, abstractmethod

from pantaray_agents.local_runtime.llm_proxy import build_local_llm_proxy_client
from pantaray_agents.schema.agent import AgentRequest, AgentResponse
from pantaray_agents.schema.agent.base import (
    AgentError,
    JSONValue,
)
from pantaray_agents.schema.repository_errors import (
    AgentRepositoryError,
    is_retryable_repository_exception,
)
from pantaray_agents.utils.prompt_loader import PromptConfig, prompt_loader
from pantaray_agents.utils.trace_context import TraceContextManager
from pantaray_llm.profiles import TOOL_THINKING_PROFILE_ID

from .error_contract import AgentErrorPhase, AgentPhaseError
from .mixins.context_utils_mixin import ContextUtilsMixin
from .mixins.error_handling_mixin import ErrorHandlingMixin
from .mixins.llm_tool_use_mixin import LlmToolUseMixin
from .tool_llm_runner import ToolLlmRunner

# ロガーの設定
logger = logging.getLogger(__name__)

type AgentConfig = dict[str, JSONValue]
type ContextDataPayload = dict[str, JSONValue]


class BaseAgent[T: AgentResponse](
    LlmToolUseMixin, ErrorHandlingMixin, ContextUtilsMixin, ABC
):
    """エージェントの基底クラス

    すべてのエージェント実装の基礎となる抽象基底クラス。
    LLMとの通信、エラーハンドリング、応答処理など共通機能を提供する。

    Attributes:
        DEFAULT_SYSTEM_INSTRUCTION (str): デフォルトのシステムプロンプト
    """

    # デフォルトのシステムプロンプト
    DEFAULT_SYSTEM_INSTRUCTION = "You are Pantaray. You must deeply understand the user's intent, underlying needs, context and circumstances surrounding the user, as well as the chronological sequence of related events. Answer in English and Japanese (use Japanese for Japan-specific cultural, social, or natural elements)."

    # LLM proxy へ送るコンテンツ合計サイズ上限（テキスト+画像）
    MAX_GEMINI_PAYLOAD_BYTES = 20 * 1024 * 1024

    def _normalize_language(self, language: str | None) -> str:
        """言語コードを正規化する（許容は 'en' / 'ja' のみ）。

        Args:
            language: 言語コード（None可）。

        Returns:
            str: 正規化済み言語コード（"en" / "ja"）。
        """

        return "ja" if language == "ja" else "en"

    def _build_language_prefix(self, language: str | None) -> str:
        """LLMの出力言語を強制するプレフィックスを生成する。

        重要:
            既存の system_instruction を置き換えず、必ず prefix として合成して使用する。

        Args:
            language: 言語コード（None可）。

        Returns:
            str: system_instruction の先頭に付与するプレフィックス。
        """

        lang = self._normalize_language(language)
        if lang == "ja":
            return (
                "You must respond in Japanese.\n"
                "Do not include English unless explicitly requested.\n"
            )
        return (
            "You must respond in English.\n"
            "Do not include Japanese unless explicitly requested.\n"
        )

    def _compose_system_instruction(
        self,
        *,
        base_instruction: str,
        language: str | None,
    ) -> str:
        """言語プレフィックスとエージェント固有の system_instruction を合成する。

        Args:
            base_instruction: 各エージェントが持つ system_instruction（YAML等）。
            language: 言語コード（None可）。

        Returns:
            str: 合成済み system_instruction。
        """

        prefix = self._build_language_prefix(language)
        return f"{prefix}\n{base_instruction}".strip()

    def _load_prompt_config(self, prompt_name: str) -> PromptConfig:
        """プロンプト設定（system_instruction と prompt）をロードする。

        方針:
            - プロンプトは `pantaray_agents/prompts/` 配下の YAML を SSOT とする。
            - プロンプトが無い状態での稼働は許容しない（fail-fast）。

        Args:
            prompt_name: プロンプト名（拡張子なし）。例: "insight", "suggestion/suggestion"

        Returns:
            PromptConfig: 読み込んだプロンプト設定。

        Raises:
            FileNotFoundError: 指定したプロンプトファイルが存在しない場合。
            ValueError: YAML の読み込み/形式が不正な場合。
        """
        try:
            return prompt_loader.load_config(prompt_name)
        except (FileNotFoundError, ValueError) as exc:
            logger.error(
                "プロンプトの読み込みに失敗しました: prompt_name=%s error=%s",
                prompt_name,
                exc,
            )
            raise

    def create_tool_llm_runner(self, *, tool_id: str) -> ToolLlmRunner:
        """ツール内部専用の LLM runner を生成する。"""

        return ToolLlmRunner(
            client=self.client,
            llm_config=self.llm_config if isinstance(self.llm_config, dict) else {},
            default_system_instruction=str(self.DEFAULT_SYSTEM_INSTRUCTION or ""),
            error_code_prefix=f"{self.get_error_code_prefix()}_{tool_id.upper()}",
            llm_inference_profile_id=TOOL_THINKING_PROFILE_ID,
        )

    def __init__(self, config: AgentConfig) -> None:
        self.config = config
        # process() 内で参照される可能性があるため、初期値を明示する（静的解析対策）。
        self._current_language: str | None = None
        llm_cfg = config.get("llm")
        self.llm_config = llm_cfg if isinstance(llm_cfg, dict) else {}

        # 依存注入: 明示的な LLM クライアントが渡された場合はそれを利用
        injected_client = config.get("llm_client")
        if injected_client is not None:
            self.client = injected_client
        else:
            self.client = build_local_llm_proxy_client()

    async def process(self, request: AgentRequest) -> AgentResponse:  # noqa: C901
        """リクエストを処理し、成功またはエラーレスポンスを返す。

        エラー時は各エラーハンドラへ委譲し、それでも適切なレスポンスが得られない場合は
        元の例外を再送出して原因の追跡性を確保する。
        """
        response: AgentResponse | None = None
        original_error: Exception | None = None
        try:
            # 0. リクエストの型変換と検証
            validated_request = await self._validate_request(request)
            # 言語設定をリクエスト単位で保持（_process_llm_response などで参照する）
            try:
                self._current_language = getattr(validated_request, "language", None)
            except Exception:
                self._current_language = None

            request_user_id = str(getattr(validated_request, "user_id", "") or "")
            request_id = getattr(validated_request, "request_id", None)
            with TraceContextManager(
                user_id=request_user_id,
                request_id=request_id if isinstance(request_id, str) else None,
            ):
                # 1. データの取得
                #
                # NOTE:
                # ここでの障害（DB/外部APIの取得失敗など）は、後段（LLM生成/保存）とは切り分けて
                # 「FETCH_CONTEXT_ERROR」として扱う。
                try:
                    context_data = await self._fetch_context_data(validated_request)
                except (
                    ConnectionError,
                    TimeoutError,
                    OSError,
                    sqlite3.Error,
                    AgentRepositoryError,
                ) as e:
                    if is_retryable_repository_exception(e):
                        raise AgentPhaseError(AgentErrorPhase.CONTEXT_FETCH, e) from e
                    original_error = e
                    try:
                        response = await self._handle_fetch_context_error(
                            e,
                            request,
                            self._get_id_attrs(),
                        )
                    except Exception as handler_err:  # noqa: BLE001
                        logger.error(
                            "fetch context error handler failed: %s", handler_err
                        )
                        raise original_error from handler_err
                    return response  # type: ignore[return-value]

                # 2. プロンプトの構築
                logger.debug("Building prompt...")

                prompt = self._build_prompt(context_data)
                logger.debug("Prompt built successfully.")

                # 3. LLMによる生成と解析（サブクラスで具体化）
                extracted_data = await self._process_llm_response(prompt)

                # 4. レスポンスの作成
                success_response: T = self._create_success_response(
                    validated_request, extracted_data
                )
                response = success_response

                # 5. 結果の保存
                try:
                    await self._save_response(success_response)
                except AgentRepositoryError as e:
                    # 保存フェーズの分類は「ステージ例外」でのみ行う。
                    # ConnectionError/TimeoutError 等は従来どおり上位の connection_error 経路へ流す。
                    original_error = e
                    try:
                        response = await self._handle_save_response_error(
                            e,
                            validated_request,
                            self._get_id_attrs(),
                        )
                        return response
                    except Exception as handler_err:  # noqa: BLE001
                        logger.error(
                            "save response error handler failed: %s", handler_err
                        )
                        raise original_error from handler_err

                # 6. 成功レスポンスを返す
                return success_response

        except AgentPhaseError as e:
            if e.phase is AgentErrorPhase.CONTEXT_FETCH:
                raise e.cause from e
            raise
        except (ValueError, TypeError) as e:
            original_error = e
            try:
                response = await self._handle_validation_error(
                    e, request, self._get_id_attrs()
                )
            except Exception as handler_err:  # ハンドラ失敗時も握りつぶさない
                logger.error("validation error handler failed: %s", handler_err)
                raise original_error from handler_err
        except (ConnectionError, TimeoutError) as e:
            original_error = e
            try:
                response = await self._handle_connection_error(
                    e, request, self._get_id_attrs()
                )
            except Exception as handler_err:
                logger.error("connection error handler failed: %s", handler_err)
                raise original_error from handler_err
        except (RuntimeError, OSError, AttributeError) as e:
            original_error = e
            try:
                response = await self._handle_system_error(
                    e, request, self._get_id_attrs()
                )
            except Exception as handler_err:
                logger.error("system error handler failed: %s", handler_err)
                raise original_error from handler_err
        except Exception as e:  # pylint: disable=broad-except
            original_error = e
            try:
                response = await self._handle_general_error(
                    e, request, self._get_id_attrs()
                )
            except Exception as handler_err:
                logger.error("general error handler failed: %s", handler_err)
                raise original_error from handler_err

        # ここに到達した場合はエラーハンドラが正常終了したが、
        # None が返った等で有効なレスポンスが得られていない。
        if response is not None:
            return response  # type: ignore

        # 原因の例外があるならそれを再送出して隠蔽を避ける
        if original_error is not None:
            raise original_error

        # 念のためのフォールバック
        raise RuntimeError(
            "Error handler failed to produce a response and no original error captured"
        )

    @abstractmethod
    async def _validate_request(self, request: AgentRequest) -> AgentRequest:
        """リクエストの検証と型変換を行う

        Args:
            request (AgentRequest): 処理するリクエスト

        Returns:
            AgentRequest: 検証済みリクエスト

        Raises:
            ValueError: リクエストが無効な場合
            TypeError: リクエストの型が不正な場合
        """

    @abstractmethod
    async def _fetch_context_data(self, request: AgentRequest) -> ContextDataPayload:
        """コンテキストデータを取得する

        Args:
            request (AgentRequest): 検証済みリクエスト

        Returns:
            ContextDataPayload: コンテキストデータ
        """

    @abstractmethod
    def _build_prompt(self, context_data: ContextDataPayload) -> str:
        """プロンプトを構築する

        Args:
            context_data (ContextDataPayload): コンテキストデータ

        Returns:
            str: 構築されたプロンプト
        """

    @abstractmethod
    async def _process_llm_response(self, prompt: str) -> ContextDataPayload:
        """LLMレスポンスを処理する

        Args:
            prompt (str): 送信するプロンプト

        Returns:
            ContextDataPayload: 抽出されたレスポンスデータ
        """

    @abstractmethod
    def _create_success_response(
        self, request: AgentRequest, extracted_data: ContextDataPayload
    ) -> T:
        """成功レスポンスを作成する

        Args:
            request (AgentRequest): 検証済みリクエスト
            extracted_data (ContextDataPayload): 抽出されたレスポンスデータ

        Returns:
            T: 作成されたレスポンス
        """

    @abstractmethod
    async def _save_response(self, response: T) -> None:
        """レスポンスを保存する

        Args:
            response (T): 保存するレスポンス
        """

    @abstractmethod
    def _get_id_attrs(self) -> dict[str, str]:
        """ID属性名とレスポンスパラメータ名の辞書を返す

        Returns:
            dict[str, str]: ID属性名とレスポンスパラメータ名の辞書
        """

    # サブクラス契約（実装側で具体タイプを返す）
    @abstractmethod
    def get_response_class(self) -> type[T]:
        """レスポンスクラスを返す。"""

    @abstractmethod
    def get_error_code_prefix(self) -> str:
        """エラーコード接頭辞を返す。"""

    # --------------
    # ミックスイン委譲（責務の一覧）
    #   - 生成系（構造化）: LLMGenerationMixin
    #   - 文脈整形/タグ抽出/テキスト分割/時刻整形: ContextUtilsMixin
    #   - エラーハンドリング: ErrorHandlingMixin
    # --------------

    @abstractmethod
    async def _handle_agent_error(
        self, error: AgentError, response_params: dict[str, object]
    ) -> T:
        """エージェント固有のエラー処理を行う

        Args:
            error (AgentError): エラー情報
            response_params (dict[str, object]): レスポンスの追加パラメータ

        Returns:
            T: エラーレスポンス
        """
