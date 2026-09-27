"""画像の拡張子とMIMEタイプの唯一の許可表。

背景:
    許可する画像形式は storage_path の検証・ローカル画像の読み出し・read ツールの
    添付判定という 3 箇所で必要になる。表が分かれていると片方だけ広がったときに
    「保存はできるが読めない」「読めるが検証を通らない」といった食い違いが生じる。

方針:
    拡張子→MIME の対応をここだけで定義し、拡張子集合とMIME集合はそこから導出する。
"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import Final

IMAGE_MIME_TYPE_BY_EXTENSION: Final[Mapping[str, str]] = MappingProxyType(
    {
        ".gif": "image/gif",
        ".jpeg": "image/jpeg",
        ".jpg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
    }
)
IMAGE_EXTENSIONS: Final = frozenset(IMAGE_MIME_TYPE_BY_EXTENSION)
IMAGE_MIME_TYPES: Final = frozenset(IMAGE_MIME_TYPE_BY_EXTENSION.values())


__all__ = [
    "IMAGE_EXTENSIONS",
    "IMAGE_MIME_TYPES",
    "IMAGE_MIME_TYPE_BY_EXTENSION",
]
