from __future__ import annotations

from pathlib import Path

from .recovery_audit_repository import (
    RecoveryAuditEvent,
    RecoveryAuditScope,
    RecoveryAuditSeverity,
    list_recovery_audit_events_for_action,
    list_recovery_audit_events_for_invocation,
    list_runtime_lock_recovery_audit_events,
)


def list_action_recovery_audit_events(
    *,
    db_path: Path,
    busy_timeout_ms: int,
    action_id: str,
) -> tuple[RecoveryAuditEvent, ...]:
    return list_recovery_audit_events_for_action(
        db_path=db_path,
        busy_timeout_ms=busy_timeout_ms,
        action_id=action_id,
    )


def list_invocation_recovery_audit_events(
    *,
    db_path: Path,
    busy_timeout_ms: int,
    invocation_id: str,
) -> tuple[RecoveryAuditEvent, ...]:
    return list_recovery_audit_events_for_invocation(
        db_path=db_path,
        busy_timeout_ms=busy_timeout_ms,
        invocation_id=invocation_id,
    )


def list_runtime_recovery_audit_events(
    *,
    db_path: Path,
    busy_timeout_ms: int,
) -> tuple[RecoveryAuditEvent, ...]:
    return list_runtime_lock_recovery_audit_events(
        db_path=db_path,
        busy_timeout_ms=busy_timeout_ms,
    )


__all__ = [
    "RecoveryAuditEvent",
    "RecoveryAuditScope",
    "RecoveryAuditSeverity",
    "list_action_recovery_audit_events",
    "list_invocation_recovery_audit_events",
    "list_runtime_recovery_audit_events",
]
