from __future__ import annotations

import sqlite3

AGENT_EXPERIENCE_RUN_COLUMNS = tuple(
    """user_id job_id action_id operation experience_id superseded_experience_id
    revision_id prompt_name prompt_version completed_at""".split()
)


def rebuild_agent_experience_extraction_runs(
    connection: sqlite3.Connection,
) -> None:
    """Allow one durable Agent Experience extraction per Action completion job."""

    connection.execute("DROP TABLE IF EXISTS agent_experience_extraction_runs_v0082")
    connection.execute(
        """
        CREATE TABLE agent_experience_extraction_runs_v0082 (
            user_id TEXT NOT NULL,
            job_id TEXT NOT NULL PRIMARY KEY,
            action_id TEXT NOT NULL,
            operation TEXT NOT NULL CHECK (
                operation IN ('no_change', 'upsert', 'supersede')
            ),
            experience_id TEXT,
            superseded_experience_id TEXT,
            revision_id TEXT,
            prompt_name TEXT NOT NULL CHECK (length(trim(prompt_name)) > 0),
            prompt_version TEXT NOT NULL CHECK (length(trim(prompt_version)) > 0),
            completed_at TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
            FOREIGN KEY (job_id) REFERENCES jobs(job_id) ON DELETE CASCADE,
            FOREIGN KEY (action_id) REFERENCES agent_actions(action_id) ON DELETE CASCADE,
            CHECK (
                (
                    operation = 'no_change'
                    AND experience_id IS NULL
                    AND superseded_experience_id IS NULL
                    AND revision_id IS NULL
                )
                OR (
                    operation = 'upsert'
                    AND experience_id IS NOT NULL
                    AND superseded_experience_id IS NULL
                    AND revision_id IS NOT NULL
                )
                OR (
                    operation = 'supersede'
                    AND experience_id IS NOT NULL
                    AND superseded_experience_id IS NOT NULL
                    AND experience_id <> superseded_experience_id
                    AND revision_id IS NOT NULL
                )
            )
        )
        """
    )
    columns = ", ".join(AGENT_EXPERIENCE_RUN_COLUMNS)
    connection.execute(
        f"""
        INSERT INTO agent_experience_extraction_runs_v0082({columns})
        SELECT {columns}
        FROM agent_experience_extraction_runs
        ORDER BY job_id
        """
    )
    connection.execute("DROP TABLE agent_experience_extraction_runs")
    connection.execute(
        """ALTER TABLE agent_experience_extraction_runs_v0082
           RENAME TO agent_experience_extraction_runs"""
    )


__all__ = [
    "AGENT_EXPERIENCE_RUN_COLUMNS",
    "rebuild_agent_experience_extraction_runs",
]
