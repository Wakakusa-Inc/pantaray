import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Query, status

from pantaray_agents.agents.core import PublicAgentHTTPError
from pantaray_agents.auth_http import get_current_user_id_from_token
from pantaray_agents.local_runtime.action_conversation.cursor_codec import (
    OpaqueCursorError,
)
from pantaray_agents.local_runtime.action_conversation.tool_output import (
    ACTION_TOOL_OUTPUT_DEFAULT_PAGE_BYTES,
    ACTION_TOOL_OUTPUT_MAX_PAGE_BYTES,
    ACTION_TOOL_OUTPUT_MIN_PAGE_BYTES,
    load_action_tool_output_detail,
)
from pantaray_agents.local_runtime.runtime.runtime_env import (
    read_local_runtime_db_config,
)
from pantaray_agents.local_runtime.storage.migrations import MigrationError
from pantaray_agents.schema.action_conversation import ActionToolOutputDetail

router = APIRouter(prefix="/v1/agents/users", tags=["Action Agent"])


@router.get(
    "/{user_id}/actions/{action_id}/steps/{step_id}/output",
    response_model=ActionToolOutputDetail,
)
def action_tool_output(
    user_id: str,
    action_id: str,
    step_id: str,
    cursor: str | None = Query(default=None),
    limit_bytes: int = Query(
        default=ACTION_TOOL_OUTPUT_DEFAULT_PAGE_BYTES,
        ge=ACTION_TOOL_OUTPUT_MIN_PAGE_BYTES,
        le=ACTION_TOOL_OUTPUT_MAX_PAGE_BYTES,
    ),
    resolved_user_id: str = Depends(get_current_user_id_from_token),
) -> ActionToolOutputDetail:
    if resolved_user_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="user_id mismatch",
        )
    try:
        db_path, busy_timeout_ms = read_local_runtime_db_config()
        detail = load_action_tool_output_detail(
            db_path=db_path,
            busy_timeout_ms=busy_timeout_ms,
            user_id=user_id,
            action_id=action_id,
            step_id=step_id,
            cursor=cursor,
            limit_bytes=limit_bytes,
        )
    except OpaqueCursorError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="invalid Action tool output cursor",
        ) from exc
    except (MigrationError, OSError, sqlite3.Error) as exc:
        raise PublicAgentHTTPError(
            "Action tool output detail failed",
            error_code="ACTION_TOOL_OUTPUT_INTEGRITY_ERROR",
        ) from exc
    if detail is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Action tool output not found",
        )
    return detail
