"""Pantaray's private app storage, which Action tools must not read.

The command sandbox denies these roots to processes; read/search paths and
command cwds are refused here with the same exceptions. The roots the app itself
places in storage for this Action (its workspace, published tool results, and
agent experience) stay readable.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from ..action_plan_document import relative_to_directory_identity
from ..outside_workspace_grant import app_owned_roots
from .broker_common import BrokerContext, BrokerPolicyError

_APP_MANAGED_ROOT_SOURCE_TYPES = frozenset({"scratch", "agent_experience"})


def private_app_storage_filter(context: BrokerContext) -> Callable[[Path], bool]:
    """Return whether a resolved path lies in storage this Action may not read.

    Built once per tool call so a directory scan does not re-resolve the roots.
    """

    storage_roots = app_owned_roots(context.db_path)
    readable_roots = tuple(
        root.canonical_real_path
        for root in context.manifest_roots
        if root.can_read and root.source_type in _APP_MANAGED_ROOT_SOURCE_TYPES
    )

    def is_private(path: Path) -> bool:
        return any(_is_within(path, root) for root in storage_roots) and not any(
            _is_within(path, root) for root in readable_roots
        )

    return is_private


def private_app_storage_error(*, code: str) -> BrokerPolicyError:
    return BrokerPolicyError(
        "This path is in Pantaray's private app storage, which tools cannot read.",
        code=code,
        fix_hint=(
            "Read Pantaray's own records (suggestions, actions, insights, "
            "activity logs, ...) with memory_sql instead of opening its files."
        ),
    )


def _is_within(path: Path, root: Path) -> bool:
    return relative_to_directory_identity(path=path, directory=root) is not None


__all__ = ["private_app_storage_error", "private_app_storage_filter"]
