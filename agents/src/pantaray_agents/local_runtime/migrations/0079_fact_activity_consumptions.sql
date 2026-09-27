CREATE TABLE fact_activity_consumptions (
    user_id TEXT NOT NULL,
    activity_log_id TEXT NOT NULL,
    fact_run_id TEXT,
    consumed_at TEXT NOT NULL,
    PRIMARY KEY (user_id, activity_log_id),
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
    FOREIGN KEY (activity_log_id) REFERENCES activity_logs(log_id) ON DELETE CASCADE,
    FOREIGN KEY (fact_run_id)
        REFERENCES agent_fact_structuring_runs(fact_run_id) ON DELETE SET NULL
);

-- Preserve the existing checkpoint's declared consumption boundary. New Fact
-- runs record each supplied Activity Description explicitly.
INSERT INTO fact_activity_consumptions(
    user_id,
    activity_log_id,
    fact_run_id,
    consumed_at
)
SELECT
    checkpoints.user_id,
    activity.log_id,
    NULL,
    checkpoints.updated_at
FROM fact_activity_checkpoints AS checkpoints
JOIN activity_logs AS activity
  ON activity.user_id = checkpoints.user_id
 AND activity.status = 'success'
 AND activity.description IS NOT NULL
 AND TRIM(activity.description) != ''
 AND (
      activity.created_at < checkpoints.last_activity_created_at
      OR (
          activity.created_at = checkpoints.last_activity_created_at
          AND activity.log_id <= checkpoints.last_activity_log_id
      )
 );

DROP TRIGGER IF EXISTS validate_fact_activity_checkpoint_insert;
DROP TRIGGER IF EXISTS validate_fact_activity_checkpoint_update;
DROP TABLE fact_activity_checkpoints;

DROP INDEX IF EXISTS idx_activity_logs_fact_batch;
CREATE INDEX idx_activity_logs_fact_pending
ON activity_logs(user_id, status, created_at, log_id);
