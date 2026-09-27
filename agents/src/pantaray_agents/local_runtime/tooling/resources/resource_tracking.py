from __future__ import annotations

import os
import uuid
from pathlib import Path

from ..models import PRODUCER_BACKED_PATH_RESOURCE_KINDS, ToolRuntimeResourceCreateInput
from .process_identity import read_process_start_signature
from .resource_repository import (
    create_tool_runtime_resource,
    mark_tool_runtime_resource_abandoned,
    mark_tool_runtime_resource_cleaned,
    mark_tool_runtime_resource_cleanup_failed,
)


def _assert_resource_scope(
    *,
    tool_invocation_id: str | None,
    action_id: str | None,
) -> None:
    if tool_invocation_id is None and action_id is None:
        raise RuntimeError(
            "tool runtime resource registration requires tool_invocation_id or action_id"
        )


def register_process_group_resource(
    *,
    db_path: Path,
    busy_timeout_ms: int,
    execution_session_id: str,
    tool_invocation_id: str | None,
    action_id: str | None,
    pid: int,
    created_at: str,
) -> str | None:
    _assert_resource_scope(tool_invocation_id=tool_invocation_id, action_id=action_id)
    pgid: int | None = None
    process_start_signature: str | None = None
    try:
        pgid = os.getpgid(pid)
    except OSError:
        pgid = None
    try:
        process_start_signature = read_process_start_signature(pid=pid)
    except Exception:
        process_start_signature = None
    resource_id = str(uuid.uuid4())
    create_tool_runtime_resource(
        db_path=db_path,
        busy_timeout_ms=busy_timeout_ms,
        resource=ToolRuntimeResourceCreateInput(
            resource_id=resource_id,
            execution_session_id=execution_session_id,
            tool_invocation_id=tool_invocation_id,
            action_id=action_id,
            resource_kind="process_group",
            status="active",
            created_at=created_at,
            pid=pid,
            pgid=pgid,
            process_start_signature=process_start_signature,
            resource_path=None,
        ),
    )
    return resource_id


def register_path_resource(
    *,
    db_path: Path,
    busy_timeout_ms: int,
    execution_session_id: str,
    tool_invocation_id: str | None,
    action_id: str | None,
    resource_kind: str,
    resource_path: Path,
    created_at: str,
) -> str | None:
    _assert_resource_scope(tool_invocation_id=tool_invocation_id, action_id=action_id)
    if resource_kind not in PRODUCER_BACKED_PATH_RESOURCE_KINDS:
        raise RuntimeError(
            f"resource kind requires an explicit producer implementation: {resource_kind}"
        )
    resource_id = str(uuid.uuid4())
    create_tool_runtime_resource(
        db_path=db_path,
        busy_timeout_ms=busy_timeout_ms,
        resource=ToolRuntimeResourceCreateInput(
            resource_id=resource_id,
            execution_session_id=execution_session_id,
            tool_invocation_id=tool_invocation_id,
            action_id=action_id,
            resource_kind=resource_kind,
            status="active",
            created_at=created_at,
            pid=None,
            pgid=None,
            process_start_signature=None,
            resource_path=str(resource_path),
        ),
    )
    return resource_id


def register_workspace_lock_resource(
    *,
    db_path: Path,
    busy_timeout_ms: int,
    execution_session_id: str,
    tool_invocation_id: str,
    action_id: str | None,
    lock_id: str,
    lock_path: Path,
    created_at: str,
) -> str | None:
    _assert_resource_scope(tool_invocation_id=tool_invocation_id, action_id=action_id)
    resource_id = str(uuid.uuid4())
    create_tool_runtime_resource(
        db_path=db_path,
        busy_timeout_ms=busy_timeout_ms,
        resource=ToolRuntimeResourceCreateInput(
            resource_id=resource_id,
            execution_session_id=execution_session_id,
            tool_invocation_id=tool_invocation_id,
            action_id=action_id,
            resource_kind="lock",
            status="active",
            created_at=created_at,
            pid=None,
            pgid=None,
            process_start_signature=None,
            resource_path=str(lock_path),
            lock_id=lock_id,
        ),
    )
    return resource_id


def mark_resource_cleaned_if_tracked(
    *,
    db_path: Path,
    busy_timeout_ms: int,
    resource_id: str | None,
    cleaned_at: str,
) -> None:
    if resource_id is None:
        return
    mark_tool_runtime_resource_cleaned(
        db_path=db_path,
        busy_timeout_ms=busy_timeout_ms,
        resource_id=resource_id,
        cleaned_at=cleaned_at,
    )


def mark_resource_cleanup_failed_if_tracked(
    *,
    db_path: Path,
    busy_timeout_ms: int,
    resource_id: str | None,
    failed_at: str,
    cleanup_error: str,
) -> None:
    if resource_id is None:
        return
    mark_tool_runtime_resource_cleanup_failed(
        db_path=db_path,
        busy_timeout_ms=busy_timeout_ms,
        resource_id=resource_id,
        failed_at=failed_at,
        cleanup_error=cleanup_error,
    )


def mark_resource_abandoned_if_tracked(
    *,
    db_path: Path,
    busy_timeout_ms: int,
    resource_id: str | None,
    abandoned_at: str,
    cleanup_error: str,
) -> None:
    if resource_id is None:
        return
    mark_tool_runtime_resource_abandoned(
        db_path=db_path,
        busy_timeout_ms=busy_timeout_ms,
        resource_id=resource_id,
        abandoned_at=abandoned_at,
        cleanup_error=cleanup_error,
    )


__all__ = [
    "mark_resource_abandoned_if_tracked",
    "mark_resource_cleaned_if_tracked",
    "mark_resource_cleanup_failed_if_tracked",
    "register_path_resource",
    "register_process_group_resource",
    "register_workspace_lock_resource",
]
