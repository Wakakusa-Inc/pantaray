"""Action tool runtime の引数検証。"""

from __future__ import annotations

from collections.abc import Mapping

from jsonschema import Draft7Validator, FormatChecker, ValidationError

from pantaray_agents.agents.action_agent.runtime.handlers.tool_args import (
    to_json_value as _to_json_value,
)
from pantaray_agents.agents.action_agent.tools import ToolDefinition
from pantaray_agents.agents.action_agent.tools.base import (
    ToolPolicyValidationError,
    ToolValidationDetails,
)
from pantaray_agents.schema.agent.base import JSONValue

from .shared import ToolValidationError

_FORMAT_CHECKER = FormatChecker()
_VALIDATOR_CACHE: dict[tuple[str, str], Draft7Validator] = {}


def validate_tool_args(tool_def: ToolDefinition, args: Mapping[str, JSONValue]) -> None:
    """ツール引数を JSON Schema で検証する。"""

    cache_key = (tool_def.tool_id, tool_def.input_schema_fingerprint)

    validator = _VALIDATOR_CACHE.get(cache_key)
    if validator is None:
        schema_for_validation = tool_def.build_validation_input_schema()
        validator = Draft7Validator(
            schema_for_validation, format_checker=_FORMAT_CHECKER
        )
        _VALIDATOR_CACHE[cache_key] = validator

    try:
        validator.validate(args)
    except ValidationError as exc:
        raise ToolValidationError(
            format_validation_error_message(exc),
            details=build_validation_error_details(exc),
        ) from exc
    if tool_def.pre_validate_args is None:
        return
    try:
        tool_def.pre_validate_args(args)
    except ToolPolicyValidationError as exc:
        raise ToolValidationError(str(exc), details=exc.details) from exc


def format_validation_error_message(exc: ValidationError) -> str:
    """jsonschema の ValidationError を短く整形する。"""

    required_error = _format_required_error(exc)
    if required_error is not None:
        return required_error

    path = list(exc.path) if getattr(exc, "path", None) is not None else []
    if path:
        return f"{'.'.join(str(p) for p in path)}: {exc.message}"
    return exc.message


def build_validation_error_details(exc: ValidationError) -> ToolValidationDetails:
    """jsonschema の ValidationError を共通 validation detail へ正規化する。"""

    message = format_validation_error_message(exc)
    metadata: dict[str, JSONValue] = {
        "validator": str(getattr(exc, "validator", "") or ""),
        "schema_path": _to_json_value(list(getattr(exc, "schema_path", []) or [])),
    }
    validator_value = getattr(exc, "validator_value", None)
    if validator_value is not None:
        metadata["validator_value"] = _to_json_value(validator_value)

    context_items: list[JSONValue] = []
    for child in list(getattr(exc, "context", []) or [])[:5]:
        if not isinstance(child, ValidationError):
            continue
        context_items.append(
            {
                "path": list(getattr(child, "path", []) or []),
                "message": str(getattr(child, "message", "")),
            }
        )
    if context_items:
        metadata["context"] = context_items

    return {
        "path": list(getattr(exc, "path", []) or []),
        "message": message,
        "metadata": metadata,
    }


def _format_required_error(exc: ValidationError) -> str | None:
    if getattr(exc, "validator", None) != "required":
        return None

    missing_field = _missing_required_field(exc)
    if missing_field is None:
        return None

    path = [str(part) for part in list(getattr(exc, "path", []) or [])]
    arg_path = ".".join([*path, missing_field])
    return (
        f"Missing required arg `{arg_path}`. "
        f"Provide `args.{arg_path}` according to the tool schema."
    )


def _missing_required_field(exc: ValidationError) -> str | None:
    required_fields = getattr(exc, "validator_value", None)
    if not isinstance(required_fields, list):
        return None
    instance = getattr(exc, "instance", None)
    if not isinstance(instance, Mapping):
        return None
    for field in required_fields:
        if isinstance(field, str) and field not in instance:
            return field
    return None
