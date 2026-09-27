"""UTC timestamp canonicalization helpers.

このモジュールは、永続 row と event payload 間で時刻表現がズレないように
UTC / microseconds fixed / Z suffix の単一契約を提供する。
"""

from __future__ import annotations

from datetime import UTC, datetime

_CANONICAL_UTC_TIMESTAMP_SUFFIX_FORMAT = "-%m-%dT%H:%M:%S.%fZ"


def _format_iso8601_utc_z(value: datetime) -> str:
    return f"{value.year:04d}{value.strftime(_CANONICAL_UTC_TIMESTAMP_SUFFIX_FORMAT)}"


def normalize_iso8601_utc_z(value: str) -> str:
    """ISO8601 datetime を canonical UTC/Z 文字列へ正規化する。

    返却形式は常に `YYYY-MM-DDTHH:MM:SS.ffffffZ` とする。
    """

    return _format_iso8601_utc_z(parse_iso8601_utc(value))


def format_iso8601_utc_z_milliseconds(value: datetime) -> str:
    """datetime を `YYYY-MM-DDTHH:MM:SS.sssZ` へ正規化する。"""

    return (
        value.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    )


def normalize_iso8601_utc_z_milliseconds(value: str) -> str:
    """ISO8601 datetime を UTC/Z millisecond 文字列へ正規化する。"""

    return format_iso8601_utc_z_milliseconds(parse_iso8601_utc(value))


def parse_iso8601_utc(value: str) -> datetime:
    """ISO8601 datetime を timezone-aware UTC datetime として parse する。"""

    if not isinstance(value, str) or not value.strip():
        raise ValueError("datetime must be a non-empty ISO8601 string")
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("invalid ISO8601 datetime") from exc
    if parsed.tzinfo is None:
        raise ValueError("timezone information is required")
    try:
        return parsed.astimezone(UTC)
    except OverflowError as exc:
        raise ValueError("datetime exceeds supported UTC range") from exc


def utc_now_iso8601_utc_z() -> str:
    """現在 UTC を canonical UTC/Z 形式で返す。"""

    return _format_iso8601_utc_z(datetime.now(UTC))
