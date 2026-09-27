"""JSON schema value types and freeze/serialization helpers for action tools."""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from types import MappingProxyType
from typing import NotRequired, Required, TypedDict, TypeGuard, overload

from pantaray_agents.schema.agent.base import JSONValue

type SchemaScalar = str | int | float | bool | None
type SchemaNode = SchemaScalar | "SchemaMapping" | "SchemaSequence"
type SchemaMapping = Mapping[str, SchemaNode]
type SchemaSequence = Sequence[SchemaNode]
type ToolValidationPath = list[str | int]


class ToolValidationDetails(TypedDict, total=False):
    """LLM が自己修復に使う validation detail の共通契約。"""

    path: Required[ToolValidationPath]
    message: Required[str]
    code: NotRequired[str]
    reason: NotRequired[str]
    metadata: NotRequired[JSONValue]


_STRING_LIKE_TYPES = (str, bytes, bytearray)


def _is_non_string_sequence(value: object) -> TypeGuard[Sequence[object]]:
    return isinstance(value, Sequence) and not isinstance(value, _STRING_LIKE_TYPES)


def _is_schema_sequence(value: SchemaNode) -> TypeGuard[SchemaSequence]:
    return isinstance(value, Sequence) and not isinstance(value, _STRING_LIKE_TYPES)


class FrozenSchemaSequence(Sequence[SchemaNode]):
    """JSON schema の配列を保持する読み取り専用シーケンス。"""

    __slots__ = ("_values",)

    def __init__(self, values: tuple[SchemaNode, ...]) -> None:
        self._values = values

    @overload
    def __getitem__(self, index: int) -> SchemaNode: ...

    @overload
    def __getitem__(self, index: slice) -> Sequence[SchemaNode]: ...

    def __getitem__(self, index: int | slice) -> SchemaNode | Sequence[SchemaNode]:
        return self._values[index]

    def __iter__(self) -> Iterator[SchemaNode]:
        return iter(self._values)

    def __len__(self) -> int:
        return len(self._values)


class FrozenSchemaMapping(Mapping[str, SchemaNode]):
    """JSON schema のオブジェクトを保持する読み取り専用マッピング。"""

    __slots__ = ("_values",)

    def __init__(self, values: Mapping[str, SchemaNode]) -> None:
        self._values = MappingProxyType(dict(values))

    def __getitem__(self, key: str) -> SchemaNode:
        return self._values[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._values)

    def __len__(self) -> int:
        return len(self._values)


def freeze_schema_node(value: object) -> SchemaNode:
    """JSON Schema 値を深く不変化する。"""

    if value is None:
        return None
    if isinstance(value, str | int | float | bool):
        return value

    if isinstance(value, Mapping):
        frozen_items: dict[str, SchemaNode] = {}
        for key, nested in value.items():
            if not isinstance(key, str):
                raise TypeError("JSON schema object key must be a string.")
            frozen_items[key] = freeze_schema_node(nested)
        return FrozenSchemaMapping(frozen_items)

    if _is_non_string_sequence(value):
        frozen_values = tuple(freeze_schema_node(item) for item in value)
        return FrozenSchemaSequence(frozen_values)

    raise TypeError(f"Unsupported JSON schema value type: {type(value).__name__}")


def schema_to_plain_json(value: SchemaNode) -> JSONValue:
    """不変スキーマを plain JSON（dict/list/scalar）へ変換する。"""

    if value is None or isinstance(value, str | int | float | bool):
        return value

    if isinstance(value, Mapping):
        return {str(key): schema_to_plain_json(nested) for key, nested in value.items()}

    if _is_schema_sequence(value):
        return [schema_to_plain_json(nested) for nested in value]

    raise TypeError(f"Unsupported frozen schema value type: {type(value).__name__}")


__all__ = [
    "FrozenSchemaMapping",
    "FrozenSchemaSequence",
    "SchemaMapping",
    "SchemaNode",
    "SchemaScalar",
    "SchemaSequence",
    "ToolValidationDetails",
    "ToolValidationPath",
    "freeze_schema_node",
    "schema_to_plain_json",
]
