"""Small normalization helpers shared by orchestration modules."""

from __future__ import annotations


def normalize_string(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def normalize_lower_string(value: object) -> str | None:
    normalized = normalize_string(value)
    if normalized is None:
        return None
    return normalized.lower()
