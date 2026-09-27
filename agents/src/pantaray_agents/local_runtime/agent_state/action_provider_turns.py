"""Read back the provider turns one Action may hand to its current connection.

A run keeps the turns it received in memory; after a restart or a follow-up it
reloads what earlier runs recorded, so the items it projects are byte for byte
the ones the provider already read. Only one account's turns come back: the
opaque part of a turn is readable by its issuer alone (migration 0116).
"""

from __future__ import annotations

import sqlite3

from pydantic import TypeAdapter

from pantaray_llm.contracts.conversation import LlmProviderTurn

_PROVIDER_TURN_ADAPTER: TypeAdapter[LlmProviderTurn] = TypeAdapter(LlmProviderTurn)


def read_action_provider_turns_in_connection(
    connection: sqlite3.Connection,
    *,
    user_id: str,
    action_id: str,
    identity: str,
) -> dict[str, LlmProviderTurn]:
    """The provider turn each LLM step of this Action produced, by ``step_id``."""

    rows = connection.execute(
        """
        SELECT step_id, provider_turn
        FROM agent_action_steps
        WHERE user_id = ?
          AND action_id = ?
          AND provider_turn IS NOT NULL
          AND provider_turn_identity = ?
        """,
        (user_id, action_id, identity),
    ).fetchall()
    return {
        str(row["step_id"]): _PROVIDER_TURN_ADAPTER.validate_json(
            str(row["provider_turn"])
        )
        for row in rows
    }


__all__ = ["read_action_provider_turns_in_connection"]
