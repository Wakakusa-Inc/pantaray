from __future__ import annotations

from pantaray_agents.local_runtime.storage.migrations import MigrationError


def normalize_optional_sqlite_bool(
    value: object,
    *,
    field_name: str,
) -> bool | None:
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, int) and value in {0, 1}:
        return bool(value)
    raise MigrationError(f"{field_name} must be stored as 0/1 or bool")


def normalize_required_sqlite_bool(
    value: object,
    *,
    field_name: str,
) -> bool:
    normalized = normalize_optional_sqlite_bool(value, field_name=field_name)
    if normalized is None:
        raise MigrationError(f"{field_name} must not be null")
    return normalized
