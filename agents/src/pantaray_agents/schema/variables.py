from datetime import datetime

from pydantic import BaseModel

from pantaray_agents.schema.agent.base import JSONValue


class CaptureData(BaseModel):
    """キャプチャデータ。"""

    content: str  # キャプチャの内容
    timestamp: datetime  # キャプチャ時刻
    metadata: dict[str, JSONValue]  # メタデータ


class InsightData(BaseModel):
    """インサイトデータの構造定義。"""

    summary: str
    categories: list[str]
    confidence: float
    created_at: datetime
    metadata: dict[str, JSONValue]


class TaskContext(BaseModel):
    """タスクコンテキスト。"""

    captures: list[CaptureData] = []  # キャプチャデータ
    insight: dict[str, JSONValue] = {}  # 分析や洞察
    memory: dict[str, JSONValue] = {}  # 長期記憶
    state: dict[str, JSONValue] = {}  # 状態管理
    tools: dict[str, JSONValue] = {}  # ツール関連データ


class AgentVariables(BaseModel):
    """エージェント変数。"""

    context: TaskContext
    task_data: dict[str, JSONValue] = {}  # タスク固有データ
    output_data: dict[str, JSONValue] | None = None  # 出力データ
