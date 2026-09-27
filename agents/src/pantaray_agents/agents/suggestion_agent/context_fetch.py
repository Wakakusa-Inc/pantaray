"""SuggestionAgent の context fetch 補助関数。"""

from typing import Protocol

from pantaray_agents.schema.repositories.repository import DBRow, RepositoryResult
from pantaray_agents.schema.repository_errors import repository_data_or_raise

from .context_density import SUMMARY_TYPES_24H_1W_1M
from .context_types import (
    ActivitySummaryRowsByType,
    SummaryType,
    normalize_activity_summary_row,
)


class ActivitySummaryRepository(Protocol):
    """24h/1w/1m summary 取得で必要な repository プロトコル。"""

    async def get_recent_activity_summary(
        self, user_id: str, *, summary_type: SummaryType, limit: int
    ) -> RepositoryResult[list[DBRow]]: ...


async def fetch_summary_rows_by_type(
    *,
    repository: ActivitySummaryRepository,
    user_id: str,
) -> ActivitySummaryRowsByType:
    """24h/1w/1m summary を取得し、型を正規化して返す。"""
    rows_by_type: ActivitySummaryRowsByType = {}
    for summary_type in SUMMARY_TYPES_24H_1W_1M:
        rows = repository_data_or_raise(
            await repository.get_recent_activity_summary(
                user_id,
                summary_type=summary_type,
                limit=1,
            ),
            safe_message=f"failed to fetch recent {summary_type} activity summary",
        )

        first_row = (rows or [None])[0]
        if not isinstance(first_row, dict):
            rows_by_type[summary_type] = None
            continue
        rows_by_type[summary_type] = normalize_activity_summary_row(first_row)
    return rows_by_type
