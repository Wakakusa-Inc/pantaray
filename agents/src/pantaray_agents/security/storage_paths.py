"""ユーザースコープ画像の Storage パス検証。

背景:
    `storage_path` は user scope の論理名であり、これを無検証で画像解決へ繋ぐと
    「他ユーザーのパス」を指定するだけで機密画像が外部へ流出し得る。

方針:
    - `storage_path` はクライアント申告を信じない（SSOTで検証する）。
    - 規約は `{user_id}/{YYYY-MM-DD}/{uuid}.{ext}` に固定する。
    - 不正な入力は fail-closed（例外）で拒否する。
"""

from __future__ import annotations

import re
from datetime import date
from uuid import UUID

from pantaray_agents.security.image_media_types import IMAGE_EXTENSIONS

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def is_valid_image_storage_path(
    *, user_id: str, storage_path: str, max_len: int = 512
) -> bool:
    """user-scoped 画像の Storage パスが規約に一致するか判定する。

    規約:
        `{user_id}/{YYYY-MM-DD}/{uuid}.{ext}`

    Args:
        user_id: 対象ユーザーID（プレフィックスとして使用）。
        storage_path: 画像の論理 storage_path。
        max_len: 許容する最大長（デフォルト512）。

    Returns:
        bool: 規約に一致する場合は True。
    """

    if not user_id.strip():
        return False

    path = storage_path.strip()
    if not path:
        return False
    if len(path) > max_len:
        return False

    # 制御文字・パストラバーサル風の入力は拒否（Storageキーでもログ/監視に悪影響）
    if any(ch in path for ch in ("\n", "\r", "\t", "\x00")):
        return False
    if ".." in path or "\\" in path:
        return False

    prefix = f"{user_id}/"
    if not path.startswith(prefix):
        return False

    rest = path[len(prefix) :]
    parts = rest.split("/")
    if len(parts) != 2:
        return False

    date_str, filename = parts
    if _DATE_RE.fullmatch(date_str) is None:
        return False
    # 正規表現だけでは 2025-99-99 のような「実在しない日付」を弾けないため、
    # ISO日付として実際に解釈できることも条件にする。
    try:
        date.fromisoformat(date_str)
    except ValueError:
        return False
    extension_index = filename.rfind(".")
    if extension_index <= 0:
        return False
    if filename[extension_index:].lower() not in IMAGE_EXTENSIONS:
        return False
    try:
        UUID(filename[:extension_index])
    except ValueError:
        return False
    return True


def validate_image_storage_path(
    *, user_id: str, storage_path: str, max_len: int = 512
) -> None:
    """user-scoped 画像の Storage パスを検証し、不正なら拒否する。"""

    if not is_valid_image_storage_path(
        user_id=user_id,
        storage_path=storage_path,
        max_len=max_len,
    ):
        raise ValueError("images[].storage_path is invalid")
