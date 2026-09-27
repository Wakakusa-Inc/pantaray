"""互換レイヤ: Repository ステージ例外の再エクスポート。

定義本体は `pantaray_agents.schema.repository_errors` に移設済み。
"""

from pantaray_agents.schema.repository_errors import (
    AgentRepositoryError,
    FetchContextError,
    RepositoryStage,
    SaveResponseError,
    StorageCommitError,
)

__all__ = [
    "AgentRepositoryError",
    "FetchContextError",
    "SaveResponseError",
    "StorageCommitError",
    "RepositoryStage",
]
