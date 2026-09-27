from __future__ import annotations

from typing import TypeGuard


def is_strict_int(value: object) -> TypeGuard[int]:
    return isinstance(value, int) and not isinstance(value, bool)


__all__ = ["is_strict_int"]
