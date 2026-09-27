"""ActionAgent ログ出力の機密縮退ヘルパー。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from traceback import extract_tb
from typing import Final, TypedDict

from pydantic import ValidationError

_MAX_LOG_KEYS: Final[int] = 12


class ValidationErrorLogFields(TypedDict):
    """ValidationError のログ出力向け要約。"""

    exception_type: str
    error_count: int
    missing_keys: list[str]
    invalid_keys: list[str]


def exception_type_name(exc: BaseException) -> str:
    """例外型名だけを返す。"""
    return type(exc).__name__


def safe_exception_origin(exc: BaseException) -> str | None:
    """例外の最終発生箇所を安全に要約する。"""
    traceback_obj = exc.__traceback__
    if traceback_obj is None:
        return None
    frames = extract_tb(traceback_obj)
    if not frames:
        return None
    last_frame = frames[-1]
    filename = Path(last_frame.filename).name or last_frame.filename
    return f"{filename}:{last_frame.lineno}:{last_frame.name}"


def safe_mapping_keys(value: object, *, max_keys: int = _MAX_LOG_KEYS) -> list[str]:
    """dict のキー一覧を安全に取得する（値は出さない）。"""
    if not isinstance(value, Mapping):
        return []
    keys = sorted(str(k) for k in value.keys())
    return keys[:max_keys]


def summarize_missing_required_string_fields(
    value: Mapping[str, object],
    *,
    required_fields: Sequence[str],
) -> list[str]:
    """required な string field の欠落一覧を返す。"""
    missing_fields: list[str] = []
    for field_name in required_fields:
        field_value = value.get(field_name)
        if not isinstance(field_value, str) or not field_value.strip():
            missing_fields.append(field_name)
    return missing_fields


def safe_value_shape(value: object, *, max_keys: int = _MAX_LOG_KEYS) -> str:
    """値の形状だけを文字列化する（機密になり得る中身は出さない）。"""
    if value is None:
        return "None"
    if isinstance(value, Mapping):
        keys = safe_mapping_keys(value, max_keys=max_keys)
        suffix = "..." if len(value) > len(keys) else ""
        return f"dict(keys={keys}{suffix})"
    if isinstance(value, str):
        return f"str(len={len(value)})"
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        return f"{type(value).__name__}(len={len(value)})"
    return type(value).__name__


def summarize_validation_error(
    exc: ValidationError, *, max_keys: int = _MAX_LOG_KEYS
) -> ValidationErrorLogFields:
    """ValidationError を機密を含まない最小情報へ要約する。"""
    missing_keys: set[str] = set()
    invalid_keys: set[str] = set()

    for item in exc.errors():
        loc_raw: object = item.get("loc", ())
        if isinstance(loc_raw, tuple):
            loc_parts = [str(part) for part in loc_raw if str(part)]
        elif isinstance(loc_raw, list):
            loc_parts = [str(part) for part in loc_raw if str(part)]
        else:
            loc_parts = [str(loc_raw)] if loc_raw else []
        key = ".".join(loc_parts) if loc_parts else "<root>"

        error_type = str(item.get("type", ""))
        if "missing" in error_type:
            missing_keys.add(key)
        else:
            invalid_keys.add(key)

    return ValidationErrorLogFields(
        exception_type=exception_type_name(exc),
        error_count=len(exc.errors()),
        missing_keys=sorted(missing_keys)[:max_keys],
        invalid_keys=sorted(invalid_keys)[:max_keys],
    )


__all__ = [
    "ValidationErrorLogFields",
    "safe_exception_origin",
    "summarize_missing_required_string_fields",
    "exception_type_name",
    "safe_mapping_keys",
    "safe_value_shape",
    "summarize_validation_error",
]
