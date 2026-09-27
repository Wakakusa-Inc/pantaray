from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, is_dataclass
from enum import Enum
from typing import TYPE_CHECKING, TypeGuard

if TYPE_CHECKING:
    from _typeshed import DataclassInstance
else:
    DataclassInstance = object


def serialize_generate_config(config: object | None) -> dict[str, object]:
    if config is None:
        return {}
    if isinstance(config, Mapping):
        source = dict(config)
    elif _is_dataclass_instance(config):
        source = asdict(config)
    else:
        source = {
            key: value for key, value in vars(config).items() if not key.startswith("_")
        }
    return {
        str(key): serialize_for_json(value)
        for key, value in source.items()
        if value is not None
    }


def serialize_for_json(value: object) -> object:
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, Enum):
        return value.value
    if _is_dataclass_instance(value):
        return {
            key: serialize_for_json(item)
            for key, item in asdict(value).items()
            if item is not None
        }
    if isinstance(value, list | tuple):
        return [serialize_for_json(item) for item in value]
    if isinstance(value, Mapping):
        return {
            str(key): serialize_for_json(item)
            for key, item in value.items()
            if item is not None
        }
    if (
        not isinstance(value, type)
        and hasattr(value, "model_dump")
        and callable(value.model_dump)
    ):
        return serialize_for_json(value.model_dump(mode="json", exclude_none=True))
    if hasattr(value, "model_json_schema") and callable(value.model_json_schema):
        return value.model_json_schema()
    raise RuntimeError(f"Unsupported LLM config value: {type(value).__name__}")


def _is_dataclass_instance(value: object) -> TypeGuard[DataclassInstance]:
    return is_dataclass(value) and not isinstance(value, type)


__all__ = ["serialize_for_json", "serialize_generate_config"]
