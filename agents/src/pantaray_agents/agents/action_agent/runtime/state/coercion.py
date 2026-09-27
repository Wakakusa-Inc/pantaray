"""値の正規化（coercion）に関する共通ユーティリティ。"""

from __future__ import annotations

from collections.abc import Callable

_INT_COERCIBLE_TYPES = (float, bytes, bytearray)


def coerce_int_with_invalid_reason(
    value: object,
    *,
    on_invalid: Callable[[str], None],
) -> int:
    """任意値を int へ正規化し、不正値理由は呼び出し側へ委譲する。

    ルール:
    - None / 空文字列は 0
    - bool は不正値として扱い、`on_invalid` を呼んで 0
    - int はそのまま返す
    - 文字列は `int(...)` で変換（失敗時は不正値）
    - その他は `int(...)` を試行（失敗時は不正値）
    """

    if value is None:
        return 0
    if isinstance(value, bool):
        on_invalid("bool is not allowed")
        return 0
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return 0
        try:
            return int(text)
        except ValueError:
            on_invalid("int conversion from string failed")
            return 0
    try:
        if isinstance(value, _INT_COERCIBLE_TYPES):
            return int(value)
        raise TypeError("unsupported value type for int coercion")
    except (TypeError, ValueError, OverflowError):
        on_invalid("int conversion failed")
        return 0


__all__ = ["coerce_int_with_invalid_reason"]
