from fastapi import APIRouter, Depends, HTTPException

from pantaray_agents.auth_http import get_current_user_id_from_token
from pantaray_agents.local_runtime.context.source_control import context_source_control
from pantaray_agents.local_runtime.memory_catalog.connection import (
    open_memory_catalog_connection,
)
from pantaray_agents.local_runtime.runtime.bootstrap import read_local_runtime_db_config
from pantaray_agents.local_runtime.runtime.identity import OwnerMismatchError
from pantaray_agents.schema.context_source import (
    SourceState,
    SourceTransition,
    SourceTransitionResult,
)

router = APIRouter(prefix="/v1/agents/users", tags=["Context Source"])


def _authorize(user_id: str, resolved_user_id: str) -> None:
    if not resolved_user_id or user_id != resolved_user_id:
        raise HTTPException(status_code=403, detail="user_id mismatch")


@router.get("/{user_id}/context-source", response_model=SourceState)
async def get_context_source(
    user_id: str, resolved_user_id: str = Depends(get_current_user_id_from_token)
) -> SourceState:
    _authorize(user_id, resolved_user_id)
    db_path, busy_timeout_ms = read_local_runtime_db_config()
    with open_memory_catalog_connection(
        db_path=db_path, busy_timeout_ms=busy_timeout_ms
    ) as connection:
        try:
            return await context_source_control.read(connection, user_id)
        except OwnerMismatchError as exc:
            raise HTTPException(status_code=403, detail="owner mismatch") from exc


@router.post(
    "/{user_id}/context-source/transitions", response_model=SourceTransitionResult
)
async def transition_context_source(
    user_id: str,
    body: SourceTransition,
    resolved_user_id: str = Depends(get_current_user_id_from_token),
) -> SourceTransitionResult:
    _authorize(user_id, resolved_user_id)
    db_path, busy_timeout_ms = read_local_runtime_db_config()
    with open_memory_catalog_connection(
        db_path=db_path, busy_timeout_ms=busy_timeout_ms
    ) as connection:
        try:
            return await context_source_control.transition(connection, user_id, body)
        except OwnerMismatchError as exc:
            raise HTTPException(status_code=403, detail="owner mismatch") from exc
