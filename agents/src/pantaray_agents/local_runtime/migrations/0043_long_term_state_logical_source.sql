CREATE TABLE agent_long_term_insight_state_rebuild (
    user_id TEXT PRIMARY KEY,
    source_insight_id TEXT NOT NULL,
    source_run_id TEXT NOT NULL,
    storage_path TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    insight_profile_brief TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
);

INSERT INTO agent_long_term_insight_state_rebuild (
    user_id,
    source_insight_id,
    source_run_id,
    storage_path,
    sha256,
    insight_profile_brief,
    created_at,
    updated_at
)
SELECT
    user_id,
    source_insight_id,
    source_run_id,
    storage_path,
    sha256,
    insight_profile_brief,
    created_at,
    updated_at
FROM agent_long_term_insight_state;

DROP TABLE agent_long_term_insight_state;

ALTER TABLE agent_long_term_insight_state_rebuild
RENAME TO agent_long_term_insight_state;
