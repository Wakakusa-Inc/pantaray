UPDATE processes
SET
    completed_at = COALESCE(
        completed_at,
        (
            SELECT j.completed_at
            FROM jobs AS j
            WHERE j.process_id = processes.process_id
              AND j.completed_at IS NOT NULL
            ORDER BY j.completed_at DESC
            LIMIT 1
        )
    ),
    current_job_id = CASE
        WHEN status IN ('completed', 'failed', 'canceled', 'success', 'error', 'abandoned')
            THEN NULL
        ELSE current_job_id
    END
WHERE status IN ('completed', 'failed', 'canceled', 'success', 'error', 'abandoned')
  AND (
      completed_at IS NULL
      OR current_job_id IS NOT NULL
  );

UPDATE job_attempts
SET
    status = CASE
        WHEN (
            SELECT j.status
            FROM jobs AS j
            WHERE j.job_id = job_attempts.job_id
        ) = 'completed' THEN 'completed'
        WHEN (
            SELECT j.status
            FROM jobs AS j
            WHERE j.job_id = job_attempts.job_id
        ) = 'canceled' THEN 'canceled'
        ELSE 'failed'
    END,
    completed_at = COALESCE(
        completed_at,
        (
            SELECT j.completed_at
            FROM jobs AS j
            WHERE j.job_id = job_attempts.job_id
        )
    ),
    error_code = CASE
        WHEN (
            SELECT j.status
            FROM jobs AS j
            WHERE j.job_id = job_attempts.job_id
        ) = 'completed' THEN error_code
        ELSE COALESCE(error_code, 'TERMINAL_STATE_REPAIRED')
    END
WHERE status = 'running'
  AND EXISTS(
      SELECT 1
      FROM jobs AS j
      WHERE j.job_id = job_attempts.job_id
        AND j.status IN ('completed', 'failed', 'canceled', 'abandoned', 'blocked')
  );

UPDATE agent_action_steps
SET
    status = CASE
        WHEN (
            SELECT ti.status
            FROM tool_invocations AS ti
            WHERE ti.step_id = agent_action_steps.step_id
            ORDER BY ti.started_at DESC
            LIMIT 1
        ) = 'completed' THEN 'success'
        ELSE 'error'
    END,
    started_at = COALESCE(
        started_at,
        (
            SELECT ti.started_at
            FROM tool_invocations AS ti
            WHERE ti.step_id = agent_action_steps.step_id
            ORDER BY ti.started_at DESC
            LIMIT 1
        )
    ),
    completed_at = COALESCE(
        completed_at,
        (
            SELECT ti.completed_at
            FROM tool_invocations AS ti
            WHERE ti.step_id = agent_action_steps.step_id
            ORDER BY ti.completed_at DESC
            LIMIT 1
        )
    )
WHERE status = 'queued'
  AND short_step_id LIKE 'synthetic-%-TOOL'
  AND EXISTS(
      SELECT 1
      FROM tool_invocations AS ti
      WHERE ti.step_id = agent_action_steps.step_id
        AND ti.completed_at IS NOT NULL
  );
