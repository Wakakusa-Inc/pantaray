from __future__ import annotations

type JSONScalar = str | int | float | bool | None
# Any/object を避け、JSON 互換型を再帰的に定義する。
# TypedDict/Protocol などの値型として利用することを前提にする。
type JSONValue = JSONScalar | list["JSONValue"] | dict[str, "JSONValue"]

__all__ = ["JSONScalar", "JSONValue"]
