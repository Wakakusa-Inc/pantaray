"""環境変数の読み取りユーティリティ。

方針:
    - 暗黙デフォルトは禁止（未設定は fail-closed）。
    - 文字列→数値の変換とバリデーションを一元化し、各所での ad-hoc な実装差をなくす。
"""

from __future__ import annotations

import os


def read_required_env(name: str) -> str:
    """必須の環境変数（非空文字列）を読み取る。"""

    raw = os.getenv(name)
    if raw is None or not str(raw).strip():
        raise RuntimeError(f"Missing required environment variable: {name}")
    return str(raw).strip()


def read_required_positive_int_env(name: str) -> int:
    """必須の環境変数（正の整数）を読み取る。

    Args:
        name: 環境変数名。

    Returns:
        正の整数。

    Raises:
        RuntimeError: 未設定、整数に変換不能、または 0 以下の場合。
    """

    raw = read_required_env(name)
    try:
        value = int(raw)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer: {raw!r}") from exc
    if value <= 0:
        raise RuntimeError(f"{name} must be a positive integer: {raw!r}")
    return value
