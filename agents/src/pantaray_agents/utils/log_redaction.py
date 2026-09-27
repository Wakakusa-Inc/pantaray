"""ログ出力の機密情報マスキング。

方針:
    - 例外メッセージや通常ログに含まれる URL クエリの機密値を伏せる。
    - トークン文字列（Bearer / token=... / AWS署名パラメータ）を伏せる。
    - 既存フォーマットを維持したまま、Formatter で最終出力をサニタイズする。
"""

from __future__ import annotations

import copy
import json
import logging
import re
from types import TracebackType
from typing import cast
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pantaray_agents.schema.agent.base import JSONValue

_REDACTED = "<redacted>"

_URL_RE = re.compile(r"https?://(?:<redacted>|[^\s'\"<>\\])+", re.IGNORECASE)

_SENSITIVE_QUERY_KEYS = {
    "token",
    "access_token",
    "refresh_token",
    "id_token",
    "authorization",
    "apikey",
    "api_key",
    "key",
    "secret",
    "signature",
    "x-amz-signature",
    "x-amz-security-token",
    "x-amz-credential",
}

_ASSIGNMENT_RE = re.compile(
    r"(?i)((?:token|access_token|refresh_token|id_token|x-amz-signature|"
    r"x-amz-security-token|x-amz-credential|signature)\s*=\s*)"
    r"(\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*'|[^\s,&]+)"
)
_TOKEN_PATTERNS = (
    re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]+"),
    re.compile(
        r"(\"(?:token|access_token|refresh_token|id_token)\"\s*:\s*\")"
        r"(?:\\.|[^\"\\])*(\")",
        re.IGNORECASE,
    ),
)


def _redact_url(url: str) -> str:
    """URL のクエリ文字列に含まれる機密値を伏せる。"""

    try:
        split = urlsplit(url)
        if not split.query:
            return url

        redacted_pairs: list[tuple[str, str]] = []
        for key, value in parse_qsl(split.query, keep_blank_values=True):
            lower_key = key.lower()
            if lower_key in _SENSITIVE_QUERY_KEYS or any(
                marker in lower_key for marker in ("token", "secret", "signature")
            ):
                redacted_pairs.append((key, _REDACTED))
            else:
                redacted_pairs.append((key, value))

        redacted_query = urlencode(redacted_pairs, doseq=True)
        return urlunsplit(
            (
                split.scheme,
                split.netloc,
                split.path,
                redacted_query,
                split.fragment,
            )
        )
    except (ValueError, TypeError):
        return url


def _redact_plain_text(text: str) -> str:
    masked = _URL_RE.sub(lambda match: _redact_url(match.group(0)), text)

    def mask_assignment(match: re.Match[str]) -> str:
        value = match.group(2)
        quote = value[0] if value[0] in "\"'" else ""
        return f"{match.group(1)}{quote}{_REDACTED}{quote}"

    masked = _ASSIGNMENT_RE.sub(mask_assignment, masked)
    for pattern in _TOKEN_PATTERNS:
        replacement = rf"\1{_REDACTED}\2" if pattern.groups == 2 else rf"\1{_REDACTED}"
        masked = pattern.sub(replacement, masked)
    return masked


def _redact_json(value: JSONValue) -> JSONValue:
    if isinstance(value, str):
        return _redact_plain_text(value)
    if isinstance(value, list):
        return [_redact_json(item) for item in value]
    if isinstance(value, dict):
        return {
            key: _REDACTED
            if key.lower() in _SENSITIVE_QUERY_KEYS
            else _redact_json(item)
            for key, item in value.items()
        }
    return value


def redact_text(text: str) -> str:
    """Mask JSON string values before serialization so delimiters are unambiguous."""
    if text.lstrip().startswith(("{", "[")):
        try:
            value = cast(JSONValue, json.loads(text))
        except json.JSONDecodeError:
            pass  # Ordinary log text may begin with a bracket without being JSON.
        else:
            return json.dumps(_redact_json(value), ensure_ascii=False)
    return _redact_plain_text(text)


class RedactingFormatter(logging.Formatter):
    """最終出力テキストをマスクする Formatter。"""

    def format(self, record: logging.LogRecord) -> str:
        safe_record = copy.copy(record)
        safe_record.msg = redact_text(record.getMessage())
        safe_record.args = ()
        if safe_record.exc_text:
            safe_record.exc_text = redact_text(safe_record.exc_text)
        if safe_record.stack_info:
            safe_record.stack_info = redact_text(safe_record.stack_info)
        return super().format(safe_record)

    def formatException(
        self,
        ei: tuple[type[BaseException], BaseException, TracebackType | None]
        | tuple[None, None, None],
    ) -> str:
        return redact_text(super().formatException(ei))


def _clone_as_redacting_formatter(
    formatter: logging.Formatter | None,
) -> RedactingFormatter:
    if formatter is None:
        return RedactingFormatter("%(message)s")

    fmt = getattr(getattr(formatter, "_style", None), "_fmt", "%(message)s")
    datefmt = formatter.datefmt
    # 現在のプロジェクトでは percent-style を使用しているため、style は '%' 固定とする。
    return RedactingFormatter(fmt=fmt, datefmt=datefmt, style="%")


def apply_redacting_formatters(logger: logging.Logger | None = None) -> None:
    """指定ロガー配下のハンドラに RedactingFormatter を適用する。"""

    target = logger or logging.getLogger()
    for handler in target.handlers:
        if isinstance(handler.formatter, RedactingFormatter):
            continue
        handler.setFormatter(_clone_as_redacting_formatter(handler.formatter))
