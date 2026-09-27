from __future__ import annotations

import sqlite3

from .specs import MigrationError

EXECUTE_ACTION_JOB_TYPE = "execute_action"


def apply_action_job_payload_enqueued_at_migration(
    connection: sqlite3.Connection,
) -> None:
    connection.execute(
        """
        UPDATE job_payloads
        SET payload_json = json_insert(
            payload_json,
            '$.enqueued_at',
            json_extract(payload_json, '$.accepted_at')
        )
        WHERE job_id IN (
            SELECT job_id
            FROM jobs
            WHERE job_type = ?
        )
          AND json_type(payload_json, '$.enqueued_at') IS NULL
          AND json_type(payload_json, '$.accepted_at') = 'text'
        """,
        (EXECUTE_ACTION_JOB_TYPE,),
    )
    invalid_row = connection.execute(
        """
        SELECT jp.job_id
        FROM job_payloads AS jp
        INNER JOIN jobs AS j ON j.job_id = jp.job_id
        WHERE j.job_type = ?
          AND json_type(jp.payload_json, '$.enqueued_at') IS NULL
        ORDER BY jp.job_id ASC
        LIMIT 1
        """,
        (EXECUTE_ACTION_JOB_TYPE,),
    ).fetchone()
    if invalid_row is not None:
        raise MigrationError(
            "execute_action job payload is missing enqueued_at after migration: "
            f"{invalid_row[0]}"
        )
