from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from pantaray_agents.local_runtime.storage.migrations import MigrationError
from pantaray_agents.local_runtime.storage.migrations.connection import (
    configure_connection,
)
from pantaray_agents.schema.repositories.repository import DBRow, RepositoryResult

_SUCCESS_STATUS = "success"


class SQLiteActivityRuntimeRepository:
    """Activity local worker 向けの read-only SQLite repository。

    目的:
        - local worker の Activity 実行を SQLite source row だけで完結させる。
        - 旧 ActivityAgentRepository(Supabase) を local queue 実行経路から切り離す。
    """

    def __init__(self, *, db_path: Path | str, busy_timeout_ms: int) -> None:
        if busy_timeout_ms <= 0:
            raise MigrationError("LOCAL_DB_BUSY_TIMEOUT_MS must be a positive integer")
        self._db_path = str(db_path)
        self._busy_timeout_ms = busy_timeout_ms

    async def get_source_data_for_summary(
        self,
        user_id: str,
        summary_type: str,
        period_start: str,
        period_end: str,
        *,
        prompt_name: str | None = None,
        prompt_version: str | None = None,
    ) -> RepositoryResult[list[DBRow]]:
        source_summary_type = _resolve_source_summary_type(summary_type)
        if source_summary_type is None:
            rows = self._fetch_activity_logs(
                user_id=user_id,
                period_start=period_start,
                period_end=period_end,
            )
            return RepositoryResult(data=rows)

        rows = self._fetch_activity_summaries(
            user_id=user_id,
            summary_type=source_summary_type,
            period_start=period_start,
            period_end=period_end,
            prompt_name=prompt_name,
            prompt_version=prompt_version,
        )
        return RepositoryResult(
            data=_select_latest_rows_by_period(_rows_with_activity(rows))
        )

    async def get_recent_activity_logs(
        self,
        user_id: str,
        limit: int = 3,
    ) -> RepositoryResult[list[DBRow]]:
        with sqlite3.connect(self._db_path) as connection:
            configure_connection(connection, self._busy_timeout_ms)
            connection.row_factory = sqlite3.Row
            rows = connection.execute(
                """
                SELECT *
                FROM activity_logs
                WHERE user_id = ?
                  AND status = ?
                ORDER BY period_end DESC
                LIMIT ?
                """,
                (user_id, _SUCCESS_STATUS, limit),
            ).fetchall()
        return RepositoryResult(data=[_normalize_activity_row(row) for row in rows])

    async def get_recent_activity_summary(
        self,
        user_id: str,
        summary_type: str,
        limit: int = 1,
    ) -> RepositoryResult[list[DBRow]]:
        with sqlite3.connect(self._db_path) as connection:
            configure_connection(connection, self._busy_timeout_ms)
            connection.row_factory = sqlite3.Row
            rows = connection.execute(
                """
                SELECT *
                FROM activity_summaries
                WHERE user_id = ?
                  AND summary_type = ?
                  AND status = ?
                ORDER BY period_end DESC
                LIMIT ?
                """,
                (user_id, summary_type, _SUCCESS_STATUS, limit),
            ).fetchall()
        return RepositoryResult(data=[_normalize_activity_row(row) for row in rows])

    async def get_activity_logs_by_period_end_range(
        self,
        *,
        user_id: str,
        period_end_from: str,
        period_end_to: str,
        limit: int = 2,
    ) -> RepositoryResult[list[DBRow]]:
        with sqlite3.connect(self._db_path) as connection:
            configure_connection(connection, self._busy_timeout_ms)
            connection.row_factory = sqlite3.Row
            rows = connection.execute(
                """
                SELECT *
                FROM activity_logs
                WHERE user_id = ?
                  AND status = ?
                  AND period_end >= ?
                  AND period_end <= ?
                ORDER BY period_end ASC
                LIMIT ?
                """,
                (user_id, _SUCCESS_STATUS, period_end_from, period_end_to, limit),
            ).fetchall()
        return RepositoryResult(data=[_normalize_activity_row(row) for row in rows])

    async def list_active_user_ids_since(
        self,
        *,
        created_at_from_iso: str,
    ) -> RepositoryResult[list[str]]:
        with sqlite3.connect(self._db_path) as connection:
            configure_connection(connection, self._busy_timeout_ms)
            rows = connection.execute(
                """
                SELECT DISTINCT user_id
                FROM activity_logs
                WHERE created_at >= ?
                ORDER BY user_id ASC
                """,
                (created_at_from_iso,),
            ).fetchall()
        return RepositoryResult(data=[str(row[0]) for row in rows if row and row[0]])

    async def get_activity_log(self, **_: object) -> RepositoryResult[DBRow]:
        raise MigrationError(
            "SQLiteActivityRuntimeRepository must not be used for activity_log persistence"
        )

    async def save_activity_log(self, **_: object) -> RepositoryResult[DBRow]:
        raise MigrationError(
            "SQLiteActivityRuntimeRepository must not be used for activity_log persistence"
        )

    async def update_activity_log(self, **_: object) -> RepositoryResult[DBRow]:
        raise MigrationError(
            "SQLiteActivityRuntimeRepository must not be used for activity_log persistence"
        )

    async def get_activity_summary(self, **_: object) -> RepositoryResult[DBRow]:
        raise MigrationError(
            "SQLiteActivityRuntimeRepository must not be used for activity_summary persistence"
        )

    async def save_activity_summary(self, **_: object) -> RepositoryResult[DBRow]:
        raise MigrationError(
            "SQLiteActivityRuntimeRepository must not be used for activity_summary persistence"
        )

    async def update_activity_summary(self, **_: object) -> RepositoryResult[DBRow]:
        raise MigrationError(
            "SQLiteActivityRuntimeRepository must not be used for activity_summary persistence"
        )

    def _fetch_activity_logs(
        self,
        *,
        user_id: str,
        period_start: str,
        period_end: str,
    ) -> list[DBRow]:
        with sqlite3.connect(self._db_path) as connection:
            configure_connection(connection, self._busy_timeout_ms)
            connection.row_factory = sqlite3.Row
            rows = connection.execute(
                """
                SELECT *
                FROM activity_logs
                WHERE user_id = ?
                  AND status = ?
                  AND period_start >= ?
                  AND period_end <= ?
                ORDER BY period_start ASC
                """,
                (user_id, _SUCCESS_STATUS, period_start, period_end),
            ).fetchall()
        return [_normalize_activity_row(row) for row in rows]

    def _fetch_activity_summaries(
        self,
        *,
        user_id: str,
        summary_type: str,
        period_start: str,
        period_end: str,
        prompt_name: str | None,
        prompt_version: str | None,
    ) -> list[DBRow]:
        query = """
            SELECT *
            FROM activity_summaries
            WHERE user_id = ?
              AND summary_type = ?
              AND status = ?
              AND period_start >= ?
              AND period_end <= ?
        """
        params: list[str] = [
            user_id,
            summary_type,
            _SUCCESS_STATUS,
            period_start,
            period_end,
        ]
        if prompt_name is not None and prompt_version is not None:
            query += """
              AND prompt_name = ?
              AND prompt_version = ?
            """
            params.extend([prompt_name, prompt_version])
        query += "\nORDER BY period_start ASC, created_at DESC"
        with sqlite3.connect(self._db_path) as connection:
            configure_connection(connection, self._busy_timeout_ms)
            connection.row_factory = sqlite3.Row
            rows = connection.execute(query, tuple(params)).fetchall()
        return [_normalize_activity_row(row) for row in rows]


def _resolve_source_summary_type(summary_type: str) -> str | None:
    source_type_map = {
        "1h": None,
        "24h": "1h",
        "1w": "24h",
        "1m": "1w",
        "3m": "1m",
    }
    if summary_type not in source_type_map:
        raise MigrationError(f"Unsupported activity summary_type: {summary_type}")
    return source_type_map[summary_type]


def _normalize_activity_row(row: sqlite3.Row) -> DBRow:
    data: DBRow = {}
    for key in row.keys():
        value = row[key]
        if key in {"error", "source_capture_paths", "source_ids"}:
            data[key] = _decode_json_column(value, column=key)
            continue
        data[key] = value
    return data


def _decode_json_column(value: object, *, column: str) -> object:
    if value is None:
        return None
    if not isinstance(value, str):
        raise MigrationError(f"{column} must be stored as JSON text")
    if not value.strip():
        return None
    try:
        return json.loads(value)
    except json.JSONDecodeError as exc:
        raise MigrationError(f"{column} must be valid JSON") from exc


def _rows_with_activity(rows: list[DBRow]) -> list[DBRow]:
    """「活動なし」の下位サマリを上位サマリの source から外す。

    ActivitySummaryAgent は source が0件の期間に定型文を `source_ids` 空で書く。
    その行を source に含めると、中身のない定型文だけを LLM に渡したうえで
    `source_ids` 非空の成功行を書いてしまい、活動のない期間が上位の階層ほど
    活動ありに見える。空の行は情報を持たないので source にしない。
    """
    return [row for row in rows if row.get("source_ids")]


def _select_latest_rows_by_period(rows: list[DBRow]) -> list[DBRow]:
    best_by_period: dict[tuple[str, str], DBRow] = {}
    for row in rows:
        period_start = str(row.get("period_start", ""))
        period_end = str(row.get("period_end", ""))
        if not period_start or not period_end:
            continue
        key = (period_start, period_end)
        previous = best_by_period.get(key)
        if previous is None:
            best_by_period[key] = row
            continue
        if _parse_iso_datetime(row.get("created_at")) > _parse_iso_datetime(
            previous.get("created_at")
        ):
            best_by_period[key] = row
    selected = list(best_by_period.values())
    selected.sort(key=lambda row: _parse_iso_datetime(row.get("period_start")))
    return selected


def _parse_iso_datetime(value: object) -> datetime:
    raw = str(value or "").strip()
    if not raw:
        return datetime.min.replace(tzinfo=UTC)
    normalized = raw.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return datetime.min.replace(tzinfo=UTC)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)
