from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Final, Literal

from pantaray_agents.local_runtime.storage.migrations import MigrationError

MemoryAgentTriggerKind = Literal[
    "memory_from_short_insight",
    "memory_from_24h_summary",
    "memory_from_action_terminal",
]

SHORT_INSIGHT_MEMORY_TRIGGER_KIND: Final[MemoryAgentTriggerKind] = (
    "memory_from_short_insight"
)
SUMMARY_MEMORY_TRIGGER_KIND: Final[MemoryAgentTriggerKind] = "memory_from_24h_summary"
ACTION_TERMINAL_MEMORY_TRIGGER_KIND: Final[MemoryAgentTriggerKind] = (
    "memory_from_action_terminal"
)
UNIFIED_MEMORY_TRIGGER_KINDS: Final[tuple[MemoryAgentTriggerKind, ...]] = (
    SHORT_INSIGHT_MEMORY_TRIGGER_KIND,
    SUMMARY_MEMORY_TRIGGER_KIND,
    ACTION_TERMINAL_MEMORY_TRIGGER_KIND,
)


class MemoryAgentTriggerIntegrityError(MigrationError):
    """A durable Memory Agent trigger violates its source or job binding."""


@dataclass(frozen=True, slots=True)
class MemoryAgentTrigger:
    user_id: str
    trigger_kind: MemoryAgentTriggerKind
    source_id: str


@dataclass(frozen=True, slots=True)
class ActionTerminalTriggerBinding:
    """The completed Action turn an Action-terminal trigger points at.

    Captured with the terminal because a following turn on the same Action
    supersedes both the published revision and the turn's last step number.
    A failed or canceled turn publishes no revision, so the evidence reference
    is absent there.
    """

    action_id: str
    action_completed_at: str
    source_action_revision_id: str | None
    turn_start_step_number: int
    turn_end_step_number: int
    action_prompt_name: str
    action_prompt_version: str
    suggestion_id: str | None


def insert_pending_memory_agent_trigger(
    *,
    connection: sqlite3.Connection,
    user_id: str,
    trigger_kind: MemoryAgentTriggerKind,
    source_id: str,
    created_at: str,
    action_terminal: ActionTerminalTriggerBinding | None = None,
) -> None:
    if not user_id.strip() or not source_id.strip() or not created_at.strip():
        raise ValueError("Memory Agent trigger identity must not be empty")
    if (trigger_kind == ACTION_TERMINAL_MEMORY_TRIGGER_KIND) != (
        action_terminal is not None
    ):
        raise ValueError(
            "only an Action terminal trigger carries a completed turn binding"
        )
    try:
        connection.execute(
            """
            INSERT INTO memory_agent_triggers(
                user_id, trigger_kind, source_id, status, dispatched_job_id,
                outcome_code, created_at, handled_at, action_id,
                action_completed_at, source_action_revision_id,
                turn_start_step_number, turn_end_step_number,
                action_prompt_name, action_prompt_version, suggestion_id
            ) VALUES (?, ?, ?, 'pending', NULL, NULL, ?, NULL,
                      ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                trigger_kind,
                source_id,
                created_at,
                None if action_terminal is None else action_terminal.action_id,
                None
                if action_terminal is None
                else action_terminal.action_completed_at,
                None
                if action_terminal is None
                else action_terminal.source_action_revision_id,
                None
                if action_terminal is None
                else action_terminal.turn_start_step_number,
                None
                if action_terminal is None
                else action_terminal.turn_end_step_number,
                None if action_terminal is None else action_terminal.action_prompt_name,
                None
                if action_terminal is None
                else action_terminal.action_prompt_version,
                None if action_terminal is None else action_terminal.suggestion_id,
            ),
        )
    except sqlite3.IntegrityError as exc:
        raise MemoryAgentTriggerIntegrityError(
            "Memory Agent trigger already exists for first source success"
        ) from exc


def require_memory_agent_trigger(
    *,
    connection: sqlite3.Connection,
    user_id: str,
    trigger_kind: MemoryAgentTriggerKind,
    source_id: str,
) -> None:
    row = connection.execute(
        """
        SELECT 1
        FROM memory_agent_triggers
        WHERE user_id = ? AND source_id = ? AND trigger_kind = ?
        """,
        (user_id, source_id, trigger_kind),
    ).fetchone()
    if row is None:
        raise MemoryAgentTriggerIntegrityError(
            "terminal source replay has no matching Memory Agent trigger"
        )


__all__ = [
    "ACTION_TERMINAL_MEMORY_TRIGGER_KIND",
    "ActionTerminalTriggerBinding",
    "MemoryAgentTriggerIntegrityError",
    "MemoryAgentTrigger",
    "MemoryAgentTriggerKind",
    "SHORT_INSIGHT_MEMORY_TRIGGER_KIND",
    "SUMMARY_MEMORY_TRIGGER_KIND",
    "UNIFIED_MEMORY_TRIGGER_KINDS",
    "insert_pending_memory_agent_trigger",
    "require_memory_agent_trigger",
]
