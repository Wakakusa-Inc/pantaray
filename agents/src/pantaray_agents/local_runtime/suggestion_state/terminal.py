from __future__ import annotations

from pantaray_agents.action_status import FinalizeActionTerminalCommand
from pantaray_agents.local_runtime.storage.transactions import immediate_transaction
from pantaray_agents.repositories.suggestion_runtime_results import (
    FinalizeActionTerminalAndProjectHistoryResult,
)
from pantaray_agents.schema.repositories.repository import RepositoryResult

from .action_terminal_projection import (
    finalize_action_terminal_projection,
    map_action_status_to_process_status,
)
from .shared import LocalSuggestionStateRepositoryBase


class LocalSuggestionStateRepositoryTerminalMixin(LocalSuggestionStateRepositoryBase):
    """Run the shared terminal projection for Suggestion-facing callers."""

    async def finalize_action_terminal_and_project_history(
        self,
        *,
        command: FinalizeActionTerminalCommand,
    ) -> RepositoryResult[FinalizeActionTerminalAndProjectHistoryResult]:
        try:
            with self._connect() as connection:
                with immediate_transaction(connection):
                    projection = finalize_action_terminal_projection(
                        connection=connection,
                        command=command,
                    )
                    connection.execute(
                        """
                        UPDATE processes
                        SET status = ?, updated_at = ?
                        WHERE process_id = ?
                        """,
                        (
                            map_action_status_to_process_status(command.action_status),
                            command.completed_at,
                            command.process_id,
                        ),
                    )
        except RuntimeError as exc:
            return RepositoryResult(error=str(exc))

        return RepositoryResult(
            data=FinalizeActionTerminalAndProjectHistoryResult(
                process_completed_sequence=projection.process_completed_sequence,
                action_status=projection.action_status,
                action_failure_code=projection.action_failure_code,
                final_output=projection.final_output,
                failure_stage=projection.failure_stage,
                failure_message_public=projection.failure_message_public,
            )
        )
