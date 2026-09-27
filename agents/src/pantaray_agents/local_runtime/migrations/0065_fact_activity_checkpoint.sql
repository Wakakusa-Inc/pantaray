CREATE TABLE fact_activity_checkpoints (
    user_id TEXT PRIMARY KEY,
    last_activity_created_at TEXT NOT NULL,
    last_activity_log_id TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
);

CREATE INDEX idx_activity_logs_fact_batch
ON activity_logs(user_id, status, created_at, log_id);

-- Existing Fact state already reflects evidence observed before its last successful
-- publication. Bootstrap the watermark at that publication time so cutover does not
-- replay the user's entire Activity history.
INSERT INTO fact_activity_checkpoints(
    user_id,
    last_activity_created_at,
    last_activity_log_id,
    updated_at
)
SELECT
    user_id,
    MAX(updated_at),
    '',
    strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
FROM agent_facts
WHERE status = 'success'
GROUP BY user_id;
