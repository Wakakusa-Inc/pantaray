"""公開API向けのエラーサニタイズを提供するユーティリティ。

目的:
    - WebSocket などの公開境界から、スタックトレースや生の例外文字列、
      内部URL/本文などが漏えいしないようにする。
    - LOG_LEVEL や環境変数の誤設定に依存せず、レスポンスに詳細が混入しないことを保証する。

方針:
    - 外向きに返す `error_message` は固定の短文を基本とする（`str(exc)` を使わない）。
    - `error_details` は原則として `request_id` のみ（相関用）に限定する。
"""

from __future__ import annotations

import re
import uuid
from typing import Final

from pantaray_agents.schema.agent.base import (
    AgentError,
    ErrorSeverity,
    ErrorType,
    JSONValue,
)
from pantaray_agents.schema.websocket.server_messages import ErrorMessage

_REQUEST_ID_PATTERN: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
PUBLIC_INTERNAL_ERROR_MESSAGE: Final[str] = (
    "The operation failed due to an internal error."
)
type ErrorDetails = dict[str, JSONValue]


def new_request_id() -> str:
    """相関ID（request_id）を生成する。

    Returns:
        UUID4 文字列。
    """

    return str(uuid.uuid4())


def normalize_request_id(value: str | None) -> str:
    """受け取った request_id を正規化し、安全に扱えるIDを返す。

    外部入力（ヘッダー等）は未検証のため、そのままログやレスポンスに出すと
    汚染・改ざん・高カーディナリティ化の原因になる。ここでは最小限の形式検証を行い、
    不正な場合は新規生成する。

    Args:
        value: `X-Request-ID` 等から取得した値。

    Returns:
        形式が妥当な場合はその値、そうでなければ新規生成した request_id。
    """

    if not value:
        return new_request_id()
    if _REQUEST_ID_PATTERN.match(value) is None:
        return new_request_id()
    return value


def public_agent_error(
    *,
    error_code: str,
    request_id: str | None,
    error_type: ErrorType = ErrorType.INTERNAL_ERROR,
    severity: ErrorSeverity = ErrorSeverity.ERROR,
    error_message: str | None = None,
) -> AgentError:
    """公開API向けの `AgentError` を生成する。

    Args:
        error_code: 外部契約として安定したエラーコード。
        request_id: 相関ID。`None` の場合は内部で生成する。
        error_type: エラー種別。
        severity: 重要度。
        error_message: 外部に返してよい短いメッセージ。未指定なら固定文言。

    Returns:
        詳細情報を含まない `AgentError`。
    """

    rid = normalize_request_id(request_id)
    message = error_message or PUBLIC_INTERNAL_ERROR_MESSAGE
    details: ErrorDetails = {"request_id": rid}
    return AgentError(
        error_type=str(error_type.value),
        error_code=str(error_code),
        error_message=str(message),
        error_details=details,
        severity=str(severity.value),
        metadata=None,
    )


def public_ws_error(
    *,
    error_code: str,
    request_id: str | None = None,
    error_type: ErrorType = ErrorType.INTERNAL_ERROR,
    severity: ErrorSeverity = ErrorSeverity.ERROR,
    error_message: str | None = None,
    extra_error_details: ErrorDetails | None = None,
) -> ErrorMessage:
    """公開WebSocket向けの `ErrorMessage` を生成する。

    Args:
        error_code: 外部契約として安定したエラーコード。
        request_id: 相関ID。未指定なら内部で生成する。
        error_message: 外部に返してよい短いメッセージ。未指定なら固定文言。
        extra_error_details: `error_details` に追加する安全な情報（例: queue 名）。

    セキュリティ:
        `error_details` は原則 `request_id` のみだが、運用上の切り分けに必要な最小情報は
        **ホワイトリストで許可**する（内部URL/トークン等が混入しないようにする）。

    Returns:
        詳細情報を含まない `ErrorMessage`。
    """

    rid = normalize_request_id(request_id)
    message = error_message or PUBLIC_INTERNAL_ERROR_MESSAGE
    details: ErrorDetails = {"request_id": rid}
    if isinstance(extra_error_details, dict) and extra_error_details:
        # 許可するキーを限定（高カーディナリティ/機密混入を防止）
        allowed = {"dependency", "queue"}
        for k, v in extra_error_details.items():
            if k not in allowed:
                continue
            if v is None:
                continue
            # 文字列のみ許可（配列/オブジェクトは返さない）
            if isinstance(v, str) and v.strip():
                details[k] = v
    return ErrorMessage(
        error_type=str(error_type.value),
        error_code=str(error_code),
        error_message=str(message),
        error_details=details,
        severity=str(severity.value),
        metadata=None,
    )
