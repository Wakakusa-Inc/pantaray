from __future__ import annotations

import sqlite3
from contextlib import closing

from fastapi import APIRouter, Depends, HTTPException, Query, status

from pantaray_agents.agents.core import PublicAgentHTTPError
from pantaray_agents.auth_http import get_current_user_id_from_token
from pantaray_agents.local_runtime.action_conversation.cursor_codec import (
    OpaqueCursorError,
)
from pantaray_agents.local_runtime.action_conversation.history_candidates import (
    register_conversation_history_casefold_sqlite,
)
from pantaray_agents.local_runtime.action_conversation.history_repository import (
    read_conversation_history_page_in_connection,
)
from pantaray_agents.local_runtime.runtime import runtime_env
from pantaray_agents.local_runtime.storage import sqlite_vector as vector
from pantaray_agents.local_runtime.storage.migrations import MigrationError
from pantaray_agents.local_runtime.storage.migrations.connection import (
    configure_connection,
)
from pantaray_agents.schema.conversation_history import (
    ConversationHistoryFilter,
    ConversationHistoryPage,
)

CONVERSATION_HISTORY_DEFAULT_PAGE_SIZE = 25
CONVERSATION_HISTORY_MAX_PAGE_SIZE = 100
CONVERSATION_HISTORY_MAX_SEARCH_CODE_POINTS = 256

router = APIRouter(prefix="/api/agent/history", tags=["Conversation History"])


@router.get("", response_model=ConversationHistoryPage)
def list_conversation_history(
    cursor: str | None = Query(default=None),
    limit: int = Query(
        CONVERSATION_HISTORY_DEFAULT_PAGE_SIZE,
        ge=1,
        le=CONVERSATION_HISTORY_MAX_PAGE_SIZE,
    ),
    status_filter: ConversationHistoryFilter = Query(default="all", alias="status"),
    search_text: str = Query(
        default="",
        max_length=CONVERSATION_HISTORY_MAX_SEARCH_CODE_POINTS,
    ),
    user_id: str = Depends(get_current_user_id_from_token),
) -> ConversationHistoryPage:
    try:
        db_path, busy_timeout_ms = runtime_env.read_local_runtime_db_config()
        with closing(sqlite3.connect(db_path)) as connection:
            connection.row_factory = sqlite3.Row
            configure_connection(connection, busy_timeout_ms)
            register_conversation_history_casefold_sqlite(connection)
            connection.execute("BEGIN")
            return read_conversation_history_page_in_connection(
                connection=connection,
                user_id=user_id,
                status=status_filter,
                search_text=search_text,
                cursor=cursor,
                limit=limit,
            )
    except OpaqueCursorError as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "invalid conversation history cursor",
        ) from exc
    except (MigrationError, sqlite3.Error, vector.SQLiteVectorExtensionError) as exc:
        raise PublicAgentHTTPError(
            "Conversation history read failed",
            error_code="CONVERSATION_HISTORY_INTEGRITY_ERROR",
        ) from exc
