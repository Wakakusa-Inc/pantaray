from __future__ import annotations

from pantaray_agents.schema.repositories.repository import DBRow, RepositoryResult

from .public_projection import normalize_history_row, normalize_process_event_row
from .shared import (
    LocalSuggestionStateRepositoryBase,
    normalize_action_row,
    normalize_suggestion_row,
)


class LocalSuggestionStateRepositoryReadMixin(LocalSuggestionStateRepositoryBase):
    async def get_suggestion(
        self,
        *,
        user_id: str,
        suggestion_id: str,
    ) -> RepositoryResult[DBRow]:
        return await self.get_suggestion_state(
            user_id=user_id,
            suggestion_id=suggestion_id,
        )

    async def get_suggestion_state(
        self,
        *,
        user_id: str,
        suggestion_id: str,
    ) -> RepositoryResult[DBRow]:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT
                    s.*,
                    COALESCE(a.action_id, reply.action_id) AS action_id,
                    p.status AS action_process_status,
                    (
                        SELECT j.status
                        FROM jobs AS j
                        WHERE j.process_id = s.action_process_id
                        ORDER BY j.scheduled_at DESC, j.job_id DESC
                        LIMIT 1
                    ) AS action_job_status,
                    (
                        SELECT COALESCE(MAX(e.sequence), 0)
                        FROM agent_process_events AS e
                        WHERE e.suggestion_id = s.suggestion_id
                    ) AS latest_public_event_sequence
                FROM agent_suggestions AS s
                LEFT JOIN agent_actions AS a
                    ON a.user_id = s.user_id
                   AND a.suggestion_id = s.suggestion_id
                LEFT JOIN agent_action_steps AS reply
                    ON reply.user_id = s.user_id
                   AND reply.source_suggestion_id = s.suggestion_id
                LEFT JOIN processes AS p
                    ON p.process_id = s.action_process_id
                WHERE s.user_id = ? AND s.suggestion_id = ?
                """,
                (user_id, suggestion_id),
            ).fetchone()
        if row is None:
            return RepositoryResult(data=None)
        return RepositoryResult(data=normalize_suggestion_row(row))

    async def get_suggestion_history_row(
        self,
        *,
        user_id: str,
        suggestion_id: str,
    ) -> RepositoryResult[DBRow]:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT *
                FROM agent_suggestion_history
                WHERE user_id = ? AND suggestion_id = ?
                LIMIT 1
                """,
                (user_id, suggestion_id),
            ).fetchone()
            if row is None:
                return RepositoryResult(data=None)
            normalized_row = normalize_history_row(row)
        return RepositoryResult(data=normalized_row)

    async def get_action(
        self,
        *,
        user_id: str,
        action_id: str,
    ) -> RepositoryResult[DBRow]:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT *
                FROM agent_actions
                WHERE user_id = ? AND action_id = ?
                """,
                (user_id, action_id),
            ).fetchone()
            if row is not None:
                return RepositoryResult(data=normalize_action_row(row))
        return RepositoryResult(data=None)

    async def get_process_events_for_detail(
        self,
        *,
        user_id: str,
        suggestion_id: str,
    ) -> RepositoryResult[list[DBRow]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM agent_process_events
                WHERE user_id = ? AND suggestion_id = ?
                ORDER BY sequence ASC
                """,
                (user_id, suggestion_id),
            ).fetchall()
        return RepositoryResult(data=[normalize_process_event_row(row) for row in rows])
