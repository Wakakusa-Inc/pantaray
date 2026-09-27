from __future__ import annotations

import hashlib
from collections.abc import Callable

from ..storage.migrations import MigrationError

REFERENCE_ID_PREFIX = "ref_"
REFERENCE_ID_HASH_LENGTH = 10
REFERENCE_ID_BASE_OFFSET = 1
REFERENCE_ID_SUFFIX_WIDTH = 2


def build_reference_id(
    *,
    target_memory_key: str,
    disambiguation_index: int = 0,
) -> str:
    normalized_target_memory_key = target_memory_key.strip()
    if not normalized_target_memory_key:
        raise MigrationError("target_memory_key must not be blank")
    if disambiguation_index < 0:
        raise MigrationError("disambiguation_index must be greater than or equal to 0")
    digest = hashlib.sha1(
        normalized_target_memory_key.encode("utf-8"),
        usedforsecurity=False,
    ).hexdigest()[:REFERENCE_ID_HASH_LENGTH]
    suffix = ""
    if disambiguation_index > 0:
        suffix = f"_{disambiguation_index + REFERENCE_ID_BASE_OFFSET:0{REFERENCE_ID_SUFFIX_WIDTH}d}"
    return f"{REFERENCE_ID_PREFIX}{digest}{suffix}"


def build_reference_ids_for_targets(
    *, target_memory_keys: tuple[str, ...]
) -> tuple[str, ...]:
    return _build_reference_ids_for_targets_with_builder(
        target_memory_keys=target_memory_keys,
        builder=build_reference_id,
    )


def _build_reference_ids_for_targets_with_builder(
    *,
    target_memory_keys: tuple[str, ...],
    builder: Callable[..., str],
) -> tuple[str, ...]:
    disambiguation_counts: dict[str, int] = {}
    used_reference_ids: set[str] = set()
    reference_ids: list[str] = []
    for target_memory_key in target_memory_keys:
        disambiguation_index = disambiguation_counts.get(target_memory_key, 0)
        while True:
            reference_id = builder(
                target_memory_key=target_memory_key,
                disambiguation_index=disambiguation_index,
            )
            if reference_id not in used_reference_ids:
                break
            disambiguation_index += 1
        disambiguation_counts[target_memory_key] = disambiguation_index + 1
        used_reference_ids.add(reference_id)
        reference_ids.append(reference_id)
    return tuple(reference_ids)


def build_activity_reference_id(
    *,
    target_memory_key: str,
    disambiguation_index: int = 0,
) -> str:
    return build_reference_id(
        target_memory_key=target_memory_key,
        disambiguation_index=disambiguation_index,
    )


def build_activity_reference_ids_for_targets(
    *, target_memory_keys: tuple[str, ...]
) -> tuple[str, ...]:
    return _build_reference_ids_for_targets_with_builder(
        target_memory_keys=target_memory_keys,
        builder=build_activity_reference_id,
    )
