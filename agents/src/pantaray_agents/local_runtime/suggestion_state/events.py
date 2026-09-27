from __future__ import annotations

from pantaray_agents.action_status import (
    ACTION_STATUS_PROCESSING,
    ACTION_TERMINAL_STATUSES,
)
from pantaray_agents.local_runtime.storage.transactions import immediate_transaction
from pantaray_agents.repositories.suggestion_runtime_results import (
    AppendProcessEventResult,
)
from pantaray_agents.schema.repositories.repository import (
    RepositoryErrorKind,
    RepositoryResult,
)

from .shared import LocalSuggestionStateRepositoryBase


class LocalSuggestionStateRepositoryEventMixin(LocalSuggestionStateRepositoryBase):
    async def append_action_pause_if_processing(
        self,
        *,
        event_id: str,
        suggestion_id: str,
        user_id: str,
        action_id: str,
        payload: dict[str, object],
    ) -> RepositoryResult[AppendProcessEventResult]:
        with self._connect() as connection:
            with immediate_transaction(connection):
                row = connection.execute(
                    """
                    SELECT actions.status
                    FROM agent_suggestions AS suggestions
                    JOIN agent_actions AS actions
                      ON (actions.user_id, actions.suggestion_id) =
                         (suggestions.user_id, suggestions.suggestion_id)
                    WHERE (suggestions.user_id, suggestions.suggestion_id,
                           actions.action_id) = (?, ?, ?)
                    """,
                    (user_id, suggestion_id, action_id),
                ).fetchone()
                if row is None:
                    return RepositoryResult(
                        error="Action is not linked to the Suggestion",
                        error_kind=RepositoryErrorKind.NOT_FOUND,
                    )
                action_status = str(row["status"])
                if action_status in ACTION_TERMINAL_STATUSES:
                    return RepositoryResult()
                if action_status != ACTION_STATUS_PROCESSING:
                    return RepositoryResult(
                        error=f"Action cannot pause from status={action_status!r}",
                        error_kind=RepositoryErrorKind.CONFLICT,
                    )
                sequence = self._append_public_process_event(
                    connection,
                    event_id=event_id,
                    process_id="",
                    suggestion_id=suggestion_id,
                    user_id=user_id,
                    action_id=action_id,
                    event_name="process_paused",
                    payload=payload,
                )
                self._rebuild_history_projection(
                    connection=connection,
                    user_id=user_id,
                    suggestion_id=suggestion_id,
                )
        return RepositoryResult(
            data=AppendProcessEventResult(sequence=sequence, inserted=True)
        )

    async def append_process_event_and_project_history(
        self,
        *,
        event_id: str,
        suggestion_id: str,
        user_id: str,
        event_name: str,
        payload: dict[str, object],
        action_id: str | None = None,
    ) -> RepositoryResult[AppendProcessEventResult]:
        with self._connect() as connection:
            with immediate_transaction(connection):
                suggestion_row = connection.execute(
                    """
                    SELECT suggestions.*,
                           actions.action_id AS action_id
                    FROM agent_suggestions AS suggestions
                    LEFT JOIN agent_actions AS actions
                      ON actions.user_id = suggestions.user_id
                     AND actions.suggestion_id = suggestions.suggestion_id
                    WHERE suggestions.user_id = ?
                      AND suggestions.suggestion_id = ?
                    """,
                    (user_id, suggestion_id),
                ).fetchone()
                if suggestion_row is None:
                    return RepositoryResult(error="Suggestion not found")
                linked_action_id = (
                    str(suggestion_row["action_id"] or "").strip() or None
                )
                if action_id is not None and action_id != linked_action_id:
                    return RepositoryResult(
                        error="Action is not linked to the Suggestion"
                    )
                resolved_action_id = linked_action_id
                sequence = self._append_public_process_event(
                    connection,
                    event_id=event_id,
                    process_id="",
                    suggestion_id=suggestion_id,
                    user_id=user_id,
                    action_id=resolved_action_id,
                    event_name=event_name,
                    payload=payload,
                )
                self._rebuild_history_projection(
                    connection=connection,
                    user_id=user_id,
                    suggestion_id=suggestion_id,
                )
        return RepositoryResult(
            data=AppendProcessEventResult(sequence=sequence, inserted=True)
        )
