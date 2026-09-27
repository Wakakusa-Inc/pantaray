"""Caller-owned snapshot composition for the public conversation history page."""

from __future__ import annotations

import sqlite3

from pantaray_agents.local_runtime.runtime.action_logical_run_authority import (
    select_action_logical_run_authorities_in_connection,
)
from pantaray_agents.schema.conversation_history import (
    ConversationHistoryFilter,
    ConversationHistoryPage,
)

from .history_candidates import read_conversation_history_candidates_in_connection
from .history_projection import (
    project_conversation_history_page,
    required_history_run_selections,
)


def read_conversation_history_page_in_connection(
    *,
    connection: sqlite3.Connection,
    user_id: str,
    status: ConversationHistoryFilter,
    search_text: str,
    cursor: str | None,
    limit: int,
) -> ConversationHistoryPage:
    """Read one strict public page inside the caller's configured transaction."""

    normalized_search = search_text.strip().casefold()
    candidates = read_conversation_history_candidates_in_connection(
        connection=connection,
        user_id=user_id,
        status=status,
        search_text=normalized_search,
        cursor=cursor,
        limit=limit,
    )
    authorities = select_action_logical_run_authorities_in_connection(
        connection=connection,
        user_id=user_id,
        selections=required_history_run_selections(candidates.candidates),
    )
    return project_conversation_history_page(
        candidate_page=candidates,
        user_id=user_id,
        normalized_search=normalized_search,
        authorities=authorities,
    )


__all__ = ["read_conversation_history_page_in_connection"]
