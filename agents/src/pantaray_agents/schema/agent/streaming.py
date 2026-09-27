"""HTTPストリーミング関連のモデル定義。

注意:
    本モジュールのモデルは NDJSON/WS などで `model_dump()` の結果を `json.dumps(...)` に渡す経路がある。
    Enum をフィールドに採用する場合、`model_dump()` が Enum オブジェクトを返すと JSON 化で失敗するため、
    `use_enum_values=True` を明示し、`model_dump()` が常に値（str）を返すようにする。
"""

from pydantic import BaseModel, ConfigDict, Field

from .base import TaskStatusType

# ストリーミング（Suggestion 共通終了データ）


class StreamEndData(BaseModel):
    """SuggestionAgent用のストリーム終了データ

    Attributes:
        suggestion_id (str): 生成された提案のID
        has_suggestion (bool): 提案が生成されたかどうか
        user_id (str): 対象ユーザーのID
        completed_at (str): 処理完了時刻（ISO 8601形式）
        status (str): 処理ステータス
        total_chunks (int): 送信されたチャンクの総数
        duration_ms (int): ストリーミング処理時間（ミリ秒）
    """

    suggestion_id: str = Field(description="生成された提案のID")
    has_suggestion: bool = Field(description="提案が生成されたかどうか")
    user_id: str = Field(description="対象ユーザーのID")
    completed_at: str = Field(description="処理完了時刻（ISO 8601形式）")
    model_config = ConfigDict(use_enum_values=True)
    status: TaskStatusType = Field(
        description="処理ステータス: processing, success, error, canceled, timeout"
    )
    total_chunks: int = Field(description="送信されたチャンクの総数")
    duration_ms: int = Field(description="ストリーミング処理時間（ミリ秒）")


class CompletionChunk(BaseModel):
    """最終出力の断片（Suggestion/Action 共通）

    Attributes:
        content (str): ユーザーへの最終ステップ出力の断片
        chunk_index (int): チャンクの順序番号（0から開始）
        timestamp (str): チャンク生成時刻（ISO 8601形式）
    """

    content: str = Field(
        description="ユーザーに送信する最終出力の断片（Suggestion/Action 共通）"
    )
    chunk_index: int = Field(description="チャンクの順序番号（0から開始）")
    timestamp: str = Field(description="チャンク生成時刻（ISO 8601形式）")


class ActionStreamEndData(BaseModel):
    """ActionAgent用のストリーム終了データ

    Attributes:
        action_id (str): 実行されたアクションのID
        suggestion_id (str): 関連する提案のID
        user_id (str): 対象ユーザーのID
        completed_at (str): 処理完了時刻（ISO 8601形式）
        status (str): 処理ステータス
        total_chunks (int): 送信されたチャンクの総数
        duration_ms (int): ストリーミング処理時間（ミリ秒）
    """

    action_id: str = Field(description="実行されたアクションのID")
    suggestion_id: str = Field(description="関連する提案のID")
    user_id: str = Field(description="対象ユーザーのID")
    completed_at: str = Field(description="処理完了時刻（ISO 8601形式）")
    model_config = ConfigDict(use_enum_values=True)
    status: TaskStatusType = Field(
        description="処理ステータス: processing, success, error, canceled, timeout"
    )
    total_chunks: int = Field(description="送信されたチャンクの総数")
    duration_ms: int = Field(description="ストリーミング処理時間（ミリ秒）")
