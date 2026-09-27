from __future__ import annotations

from pantaray_agents.local_runtime.storage.migrations import MigrationError

from .models import MemoryKeyParts

MEMORY_KEY_DELIMITER = ":"
ALLOWED_MEMORY_KEY_SOURCES = frozenset(
    {
        "activity_log",
        "activity_summary",
        "short_term_insight",
        "long_term_insight",
        "fact",
    }
)


def build_memory_key(*, source: str, record_id: str) -> str:
    normalized_source = _require_non_blank("source", source)
    normalized_record_id = _require_non_blank("record_id", record_id)
    if MEMORY_KEY_DELIMITER in normalized_source:
        raise MigrationError("source must not contain ':'")
    if normalized_source not in ALLOWED_MEMORY_KEY_SOURCES:
        raise MigrationError(
            "source must be one of: " + ", ".join(sorted(ALLOWED_MEMORY_KEY_SOURCES))
        )
    return f"{normalized_source}{MEMORY_KEY_DELIMITER}{normalized_record_id}"


def split_memory_key(memory_key: str) -> MemoryKeyParts:
    normalized = _require_non_blank("memory_key", memory_key)
    source, delimiter, record_id = normalized.partition(MEMORY_KEY_DELIMITER)
    if delimiter != MEMORY_KEY_DELIMITER:
        raise MigrationError("memory_key must be formatted as '<source>:<record_id>'")
    normalized_source = _require_non_blank("memory_key source", source)
    normalized_record_id = _require_non_blank("memory_key record_id", record_id)
    if normalized_source not in ALLOWED_MEMORY_KEY_SOURCES:
        raise MigrationError(
            "memory_key source must be one of: "
            + ", ".join(sorted(ALLOWED_MEMORY_KEY_SOURCES))
        )
    return MemoryKeyParts(source=normalized_source, record_id=normalized_record_id)


def _require_non_blank(name: str, value: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise MigrationError(f"{name} must not be blank")
    return normalized
