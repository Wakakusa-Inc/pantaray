"""Budget validation helpers shared across repository write paths."""

from __future__ import annotations

from pantaray_agents.utils.strict_numbers import is_strict_int


def validate_optional_positive_int(*, field_name: str, value: int | None) -> str | None:
    """Return a repository-style validation error for non-positive values."""

    if value is None:
        return None
    if not is_strict_int(value):
        return f"{field_name} must be a positive integer or null"
    if value <= 0:
        return f"{field_name} must be a positive integer or null"
    return None
