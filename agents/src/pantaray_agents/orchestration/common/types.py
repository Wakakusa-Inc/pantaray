"""オーケストレーションで使用する厳密なJSON型・ハンドラー型の別名定義。"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Literal

# Strict JSON value types (no Any)
JSONScalar = str | int | float | bool | None
JSONValue = JSONScalar | list["JSONValue"] | dict[str, "JSONValue"]
type EventPayload = dict[str, JSONValue]

# NDJSON event names we expect from action agent streams
NDJSONEventName = Literal["stream_end", "error"]

# Callback type for NDJSON streaming lines
OnEventHandler = Callable[[NDJSONEventName, EventPayload], Awaitable[None]]
