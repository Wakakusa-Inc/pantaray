-- Version 0065 inferred a consumed-Activity watermark from the last successful
-- Fact publication timestamp. Publication time cannot prove which Activity rows
-- were supplied to that run, so those synthetic checkpoints can skip evidence
-- created while the run was in flight. Runtime-written checkpoints always store
-- the concrete Activity log_id that was supplied to a successful Fact run.
DELETE FROM fact_activity_checkpoints
WHERE last_activity_log_id = '';

CREATE TRIGGER IF NOT EXISTS validate_fact_activity_checkpoint_insert
BEFORE INSERT ON fact_activity_checkpoints
FOR EACH ROW
WHEN NOT EXISTS (
    SELECT 1
    FROM activity_logs
    WHERE user_id = NEW.user_id
      AND log_id = NEW.last_activity_log_id
      AND created_at = NEW.last_activity_created_at
      AND status = 'success'
      AND description IS NOT NULL
      AND TRIM(description) != ''
)
BEGIN
    SELECT RAISE(
        ABORT,
        'Fact activity checkpoint must identify consumed successful Activity evidence'
    );
END;

CREATE TRIGGER IF NOT EXISTS validate_fact_activity_checkpoint_update
BEFORE UPDATE OF last_activity_created_at, last_activity_log_id, user_id
ON fact_activity_checkpoints
FOR EACH ROW
WHEN NOT EXISTS (
    SELECT 1
    FROM activity_logs
    WHERE user_id = NEW.user_id
      AND log_id = NEW.last_activity_log_id
      AND created_at = NEW.last_activity_created_at
      AND status = 'success'
      AND description IS NOT NULL
      AND TRIM(description) != ''
)
BEGIN
    SELECT RAISE(
        ABORT,
        'Fact activity checkpoint must identify consumed successful Activity evidence'
    );
END;
