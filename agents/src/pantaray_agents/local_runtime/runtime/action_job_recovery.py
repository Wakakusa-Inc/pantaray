from __future__ import annotations

import sqlite3

ACTION_JOB_OPERATIONAL_RETRY_ERROR_CODE = "ACTION_JOB_OPERATIONAL_RETRY"


def is_recovered_user_step_resume(
    *,
    connection: sqlite3.Connection,
    job_id: str,
    process_id: str,
    action_id: str,
    user_id: str,
    command_id: str,
    accepted_at: str,
    suggestion_id: str | None,
) -> bool:
    row = connection.execute(
        """
        SELECT 1
        FROM jobs
        JOIN processes ON processes.process_id = jobs.process_id
          AND processes.current_job_id = jobs.job_id
        JOIN job_attempts AS active_attempt
          ON active_attempt.job_id = jobs.job_id
          AND active_attempt.attempt_number = jobs.attempt
          AND active_attempt.status = 'running'
        JOIN job_attempts AS recovered_attempt
          ON recovered_attempt.job_id = jobs.job_id
          AND recovered_attempt.attempt_number = (
            SELECT MAX(candidate.attempt_number)
            FROM job_attempts AS candidate
            WHERE candidate.job_id = jobs.job_id
              AND candidate.attempt_number < jobs.attempt
              AND candidate.error_code IN (
                  'RECOVERY_REQUEUED', :operational_retry_error_code
              )
          )
          AND recovered_attempt.status = 'failed'
          AND recovered_attempt.completed_at IS NOT NULL
        JOIN process_events AS started
          ON started.process_id = processes.process_id
          AND started.event_id = jobs.job_id || '-process-started'
          AND started.event_name = 'process_started'
        LEFT JOIN agent_process_events AS public_started
          ON public_started.event_id = started.event_id
        WHERE jobs.job_id = :job_id
          AND jobs.user_id = :user_id AND jobs.job_type = 'execute_action'
          AND jobs.status = 'running' AND jobs.logical_key = :action_id
          AND processes.user_id = :user_id AND processes.kind = 'action'
          AND processes.status = 'running' AND processes.action_id = :action_id
          AND (
            SELECT COUNT(*)
            FROM job_attempts AS intervening_attempt
            WHERE intervening_attempt.job_id = jobs.job_id
              AND intervening_attempt.attempt_number > recovered_attempt.attempt_number
              AND intervening_attempt.attempt_number < jobs.attempt
              AND intervening_attempt.status = 'failed'
              AND intervening_attempt.error_code = 'LOCAL_JOB_DISPATCH_FAILED'
              AND intervening_attempt.completed_at IS NOT NULL
          ) = jobs.attempt - recovered_attempt.attempt_number - 1
          AND json_extract(started.payload_json, '$.kind') = 'action'
          AND json_extract(started.payload_json, '$.process_id') = :process_id
          AND json_extract(started.payload_json, '$.action_id') = :action_id
          AND json_extract(started.payload_json, '$.command_id') = :command_id
          AND json_extract(started.payload_json, '$.accepted_at') = :accepted_at
          AND json_extract(started.payload_json, '$.started_at') = started.created_at
          AND (
            (:suggestion_id IS NULL
              AND json_type(started.payload_json, '$.suggestion_id') IS NULL
              AND json_type(started.payload_json, '$.persisted_sequence') IS NULL
              AND public_started.event_id IS NULL)
            OR
            (:suggestion_id IS NOT NULL
              AND json_extract(started.payload_json, '$.suggestion_id') = :suggestion_id
              AND json_extract(started.payload_json, '$.persisted_sequence') = public_started.sequence
              AND public_started.suggestion_id = :suggestion_id
              AND public_started.user_id = :user_id
              AND public_started.action_id = :action_id
              AND public_started.event_name = 'process_started'
              AND public_started.created_at = started.created_at
              AND json_extract(public_started.payload, '$.data.suggestion_id') = :suggestion_id
              AND json_extract(public_started.payload, '$.data.command_id') = :command_id
              AND json_extract(public_started.payload, '$.data.process_id') = :process_id
              AND json_extract(public_started.payload, '$.data.action_id') = :action_id
              AND json_extract(public_started.payload, '$.data.accepted_at') = :accepted_at
              AND json_extract(public_started.payload, '$.data.started_at') = started.created_at)
          )
        LIMIT 1
        """,
        {
            "job_id": job_id,
            "process_id": process_id,
            "action_id": action_id,
            "user_id": user_id,
            "command_id": command_id,
            "accepted_at": accepted_at,
            "suggestion_id": suggestion_id,
            "operational_retry_error_code": ACTION_JOB_OPERATIONAL_RETRY_ERROR_CODE,
        },
    ).fetchone()
    return row is not None


__all__ = [
    "ACTION_JOB_OPERATIONAL_RETRY_ERROR_CODE",
    "is_recovered_user_step_resume",
]
