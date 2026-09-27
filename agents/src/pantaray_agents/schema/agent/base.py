"""エージェントの基底スキーマ定義"""

from __future__ import annotations

from enum import StrEnum
from typing import TypedDict

from pydantic import BaseModel, Field

from pantaray_llm.contracts.json_value import JSONScalar as JSONScalar
from pantaray_llm.contracts.json_value import JSONValue as JSONValue

LanguageCode = str


class ErrorSeverity(StrEnum):
    """エラーの重要度を定義する列挙型"""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class ErrorType(StrEnum):
    """エラーの種類を定義する列挙型"""

    VALIDATION_ERROR = "validation_error"
    AUTHENTICATION_ERROR = "authentication_error"
    AUTHORIZATION_ERROR = "authorization_error"
    CONFLICT_ERROR = "conflict_error"
    CAPACITY_ERROR = "capacity_error"
    RATE_LIMIT_ERROR = "rate_limit_error"
    LLM_API_ERROR = "llm_api_error"
    LLM_OUTPUT_ERROR = "llm_output_error"
    TOOL_EXECUTION_ERROR = "tool_execution_error"
    REPOSITORY_ERROR = "repository_error"
    DEPENDENCY_ERROR = "dependency_error"
    TIMEOUT_ERROR = "timeout_error"
    CANCELED_ERROR = "canceled_error"
    INTERNAL_ERROR = "internal_error"


class StatusType(StrEnum):
    """処理状態を定義する列挙型"""

    SUCCESS = "success"
    ERROR = "error"
    PROCESSING = "processing"


class TaskStatusType(StrEnum):
    """タスク処理状態を定義する列挙型（外部公開用）。

    方針:
        - 外部API（特に stream_end.status）に `queued` は出さない。
        - canceled/timeout を型で表現し、仕様書と実装を一致させる。
    """

    SUCCESS = "success"
    ERROR = "error"
    PROCESSING = "processing"
    CANCELED = "canceled"  # 統一されたスペル
    TIMEOUT = "timeout"


class StepStatusType(StrEnum):
    """ステップ（agent_action_steps）処理状態を定義する列挙型（内部用）。

    背景:
        `agent_action_steps.status` は DB 制約上 `queued` を含むが、`canceled` は含まない。
        そのため「タスクの公開状態」とは別の型として分離する。
    """

    QUEUED = "queued"
    PROCESSING = "processing"
    SUCCESS = "success"
    ERROR = "error"
    TIMEOUT = "timeout"


class AgentError(BaseModel):
    """エージェントのエラー情報を表す構造

    API仕様書の統一方針に従い、HTTP API、HTTPストリーミング、WebSocket、
    データベースの全てで同じ構造を使用します。

    Attributes:
        error_type (str): エラーの種類
        error_code (str): エラーコード
        error_message (str | None): エラーメッセージ
        error_details (dict[str, JSONValue] | None): エラーの詳細情報（任意のJSONオブジェクト）
        severity (str): 重要度
        metadata (dict[str, JSONValue] | None): 追加のメタデータ（任意のJSONオブジェクト）
    """

    error_type: str = Field(description="Canonical error category defined by ErrorType")
    error_code: str = Field(description="エラーコード (例: SUGGESTION_LLM_ERROR)")
    error_message: str | None = Field(default=None, description="エラーメッセージ")
    error_details: dict[str, JSONValue] | None = Field(
        default=None, description="エラーの詳細情報（任意のJSONオブジェクト）"
    )
    severity: str = Field(description="重要度: info, warning, error, critical")
    metadata: dict[str, JSONValue] | None = Field(
        default=None, description="追加のメタデータ（任意のJSONオブジェクト）"
    )


class UserAction(BaseModel):
    """ユーザーアクション情報の構造"""

    id: str
    action_type: str
    action_data: dict[str, JSONValue]
    created_at: str | None
    user_id: str | None


class AgentContext(TypedDict):
    """エージェント共通のコンテキストデータ"""

    task_id: str
    user_id: str | None
    metadata: dict[str, JSONValue]
    user_actions: list[UserAction]


# ストリーミング系の詳細な型は schema/agent/streaming.py のモデルを参照


class AgentRequest(BaseModel):
    """エージェントリクエストの基底クラス

    全エージェントで共通して必要なフィールドのみを定義する。
    各エージェント固有のフィールドは、それぞれのリクエストクラスで定義する。
    """

    language: str | None = Field(
        default=None,
        description="UI言語。'en' または 'ja'。未指定の場合はサーバー側で解決する。",
        pattern="^(en|ja)$",
    )
    workspace_context_prompt: str | None = Field(
        default=None,
        description=(
            "登録済みの組織、プロジェクト、ローカルフォルダを任意文脈として渡す"
            "レンダリング済みプロンプト断片。未登録または未使用時はNone。"
        ),
    )


class AgentResponse(BaseModel):
    """エージェントレスポンスの基底クラス

    各エージェントは、この基底クラスを継承して具体的なレスポンス型を定義する。
    例：SuggestionAgentResponse, ActionAgentResponse など

    Attributes:
        created_at (str): レスポンス生成時刻（ISO 8601形式、UTC、サーバー側で自動付与）
        status (str): 処理ステータス。

            レスポンス契約として、少なくとも以下を許容する:
            - success: 正常完了
            - error: エラー終了
            - processing: 実行中
            - canceled: ユーザーによる中断
            - timeout: タイムアウト

            注記:
            - 非タスク系エージェントは通常 success/error/processing のみを返す。
            - タスク系（Suggestion/Action のストリーミング等）は canceled/timeout を返しうる。
        error (AgentError | None): エラー情報
    """

    created_at: str = Field(
        description="レスポンス生成時刻（ISO 8601形式、UTC、サーバー側で自動付与）"
    )
    status: str = Field(
        description=(
            "処理ステータス: success, error, processing, canceled, timeout "
            "(タスク系では canceled/timeout が返ることがある)"
        )
    )
    error: AgentError | None = Field(default=None, description="エラー情報")
