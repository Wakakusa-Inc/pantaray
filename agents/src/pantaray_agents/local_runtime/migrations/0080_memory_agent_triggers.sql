CREATE TABLE memory_agent_triggers (
    user_id TEXT NOT NULL,
    trigger_kind TEXT NOT NULL CHECK (trigger_kind IN (
        'insight_from_1h_summary',
        'insight_update_from_insight',
        'fact_from_24h_summary'
    )),
    source_id TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN (
        'pending', 'dispatched', 'skipped', 'blocked'
    )),
    dispatched_job_id TEXT,
    outcome_code TEXT,
    created_at TEXT NOT NULL,
    handled_at TEXT,
    PRIMARY KEY (user_id, trigger_kind, source_id),
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
    FOREIGN KEY (dispatched_job_id) REFERENCES jobs(job_id),
    CHECK (
        (status = 'pending'
            AND dispatched_job_id IS NULL
            AND outcome_code IS NULL
            AND handled_at IS NULL)
        OR
        (status = 'dispatched'
            AND dispatched_job_id IS NOT NULL
            AND outcome_code = 'JOB_ENQUEUED'
            AND handled_at IS NOT NULL)
        OR
        (status IN ('skipped', 'blocked')
            AND dispatched_job_id IS NULL
            AND outcome_code IS NOT NULL
            AND handled_at IS NOT NULL)
    )
);

CREATE INDEX idx_memory_agent_triggers_pending
ON memory_agent_triggers(user_id, status, created_at, source_id);
