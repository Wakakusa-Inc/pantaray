"""リポジトリ関連のスキーマ定義と共通型。

JSON値/DB行の型エイリアスと、リポジトリ境界の結果型を提供する。"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field, JsonValue

type JSONValue = JsonValue
type DBRow = dict[str, JSONValue]
type DBRows = list[DBRow]


class RepositoryErrorKind(StrEnum):
    """リポジトリ境界で扱う失敗カテゴリ。"""

    VALIDATION = "validation"
    AUTHORIZATION = "authorization"
    NOT_FOUND = "not_found"
    CONSTRAINT = "constraint"
    CONFLICT = "conflict"
    TRANSIENT = "transient"
    UNKNOWN = "unknown"


class RepositoryResult[T](BaseModel):
    """リポジトリの操作結果を表す基本クラス。"""

    data: T | None = None
    error: str | None = None
    error_kind: RepositoryErrorKind | None = None
    retryable: bool | None = None
    metadata: dict[str, JSONValue] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
