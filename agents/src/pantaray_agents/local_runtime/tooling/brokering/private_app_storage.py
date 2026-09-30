"""Pantaray's private app storage, which agent tools must not read or change.

The command sandbox denies these roots to processes; Action read/search/write
paths and command cwds are refused here with the same exceptions. The roots the
app itself places in storage for this Action (its workspace, published tool
results, and agent experience) stay usable with the access their manifest root
grants. Suggestion file tools have no such roots and see none of the storage.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from ..action_plan_document import relative_to_directory_identity
from ..outside_workspace_grant import app_owned_roots
from .broker_common import BrokerContext, BrokerPolicyError

_APP_MANAGED_ROOT_SOURCE_TYPES = frozenset({"scratch", "agent_experience"})
PRIVATE_APP_STORAGE_MESSAGE = (
    "This path is in Pantaray's private app storage, which tools cannot read or change."
)


def private_app_storage_filter(context: BrokerContext) -> Callable[[Path], bool]:
    """Return whether a resolved path lies in storage this Action may not use.

    Built once per tool call so a directory scan does not re-resolve the roots.
    """

    storage_roots = app_owned_roots(context.db_path)
    readable_roots = tuple(
        root.canonical_real_path
        for root in context.manifest_roots
        if root.can_read and root.source_type in _APP_MANAGED_ROOT_SOURCE_TYPES
    )
    return lambda path: (
        is_within_any(path, storage_roots) and not is_within_any(path, readable_roots)
    )


def private_app_storage_error(*, code: str) -> BrokerPolicyError:
    return BrokerPolicyError(
        PRIVATE_APP_STORAGE_MESSAGE,
        code=code,
        fix_hint=(
            "Read Pantaray's own records (suggestions, actions, insights, "
            "activity logs, ...) with memory_sql instead of opening its files."
        ),
    )


def is_within_any(path: Path, roots: tuple[Path, ...]) -> bool:
    # Directory identity, so a case alias on APFS cannot step around a root.
    return any(
        relative_to_directory_identity(path=path, directory=root) is not None
        for root in roots
    )


__all__ = [
    "PRIVATE_APP_STORAGE_MESSAGE",
    "is_within_any",
    "private_app_storage_error",
    "private_app_storage_filter",
]
