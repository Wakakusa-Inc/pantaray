"""ActivitySummaryAgent のスキーマ定義"""

from pydantic import Field

from .base import AgentRequest, AgentResponse


class ActivitySummaryAgentRequest(AgentRequest):
    """ActivitySummaryAgentのリクエスト

    階層的なサマリ（1h/24h/1w/1m/3m）を生成する。

    Attributes:
        user_id (str): 対象ユーザーID (UUIDv4)
        summary_id (str): バックエンドで生成したサマリID（UUIDv5: 決定的IDを推奨）
        summary_type (str): サマリの時間粒度（1h, 24h, 1w, 1m, 3m）
        period_start (str): 対象期間の開始時刻（ISO 8601形式）
        period_end (str): 対象期間の終了時刻（ISO 8601形式）
    """

    user_id: str = Field(description="対象ユーザーID")
    summary_id: str = Field(description="バックエンドで生成したサマリID")
    summary_type: str = Field(
        description="サマリの時間粒度",
        pattern="^(1h|24h|1w|1m|3m)$",
    )
    period_start: str = Field(description="対象期間の開始時刻（ISO 8601形式）")
    period_end: str = Field(description="対象期間の終了時刻（ISO 8601形式）")


class ActivitySummaryAgentResponse(AgentResponse):
    """ActivitySummaryAgentのレスポンス

    Attributes:
        summary_id (str): サマリID
        user_id (str): 対象ユーザーID
        summary_type (str): サマリの時間粒度
        summary (str): 生成されたサマリテキスト（本文）
        thinking (str | None): 思考プロセス（best-effort、取得できない場合はNone）
        period_start (str): 対象期間の開始時刻
        period_end (str): 対象期間の終了時刻
        source_ids (list[str]): 生成に使用したソースのIDリスト（activity_logs.log_id または下位サマリID）
    """

    summary_id: str = Field(description="サマリID")
    user_id: str = Field(description="対象ユーザーID")
    summary_type: str = Field(description="サマリの時間粒度")
    summary: str = Field(
        default="",
        description="生成されたサマリテキスト（本文。タグは前提にしない）",
    )
    thinking: str | None = Field(
        default=None,
        description="思考プロセス（Gemini thoughtのbest-effort、取得できない場合はNone）",
    )
    period_start: str = Field(description="対象期間の開始時刻")
    period_end: str = Field(description="対象期間の終了時刻")
    source_ids: list[str] = Field(
        default_factory=list,
        description="生成に使用したソースのIDリスト（activity_logs.log_id または下位サマリID）",
    )
