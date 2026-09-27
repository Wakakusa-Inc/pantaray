UPDATE job_attempts
SET
    status = 'canceled',
    completed_at = COALESCE(
        completed_at,
        strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
    ),
    error_code = COALESCE(error_code, 'POST_ACTION_PIPELINE_RETIRED'),
    error_message = COALESCE(error_message, 'Post-action pipeline was retired')
WHERE status = 'running'
  AND job_id IN (
      SELECT job_id
      FROM jobs
      WHERE job_type = 'post_action_pipeline'
  );

UPDATE jobs
SET
    status = 'canceled',
    claimed_by = NULL,
    claimed_at = NULL,
    heartbeat_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now'),
    cancel_requested_at = COALESCE(
        cancel_requested_at,
        strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
    ),
    next_retry_at = NULL,
    completed_at = COALESCE(
        completed_at,
        strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
    ),
    error_code = COALESCE(error_code, 'POST_ACTION_PIPELINE_RETIRED')
WHERE job_type = 'post_action_pipeline'
  AND status IN ('queued', 'running', 'paused', 'retryable_error', 'blocked');

UPDATE processes
SET
    status = 'canceled',
    updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now'),
    completed_at = COALESCE(
        completed_at,
        strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
    ),
    heartbeat_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now'),
    current_job_id = NULL
WHERE kind = 'post_action_pipeline'
  AND status NOT IN (
      'completed', 'failed', 'canceled', 'success', 'error', 'abandoned'
  );

DROP INDEX IF EXISTS idx_activity_summaries_fact_followup_fact_id;
ALTER TABLE activity_summaries DROP COLUMN fact_followup_fact_id;
ALTER TABLE activity_summaries DROP COLUMN fact_followup_enqueued_at;
