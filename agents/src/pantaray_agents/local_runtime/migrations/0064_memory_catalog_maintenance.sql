ALTER TABLE memory_repair_queue RENAME TO memory_repair_queue_v0063;

CREATE TABLE memory_repair_queue (
    user_id TEXT NOT NULL,
    node_id TEXT NOT NULL,
    detected_revision_id TEXT NOT NULL,
    reason TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('pending', 'completed')),
    attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
    next_attempt_at TEXT NOT NULL,
    last_error_code TEXT,
    created_at TEXT NOT NULL,
    completed_at TEXT,
    PRIMARY KEY (user_id, node_id, detected_revision_id, reason),
    FOREIGN KEY (user_id, node_id)
        REFERENCES memory_nodes(user_id, node_id) ON DELETE CASCADE,
    FOREIGN KEY (user_id, detected_revision_id)
        REFERENCES memory_revisions(user_id, revision_id) ON DELETE CASCADE
);

INSERT INTO memory_repair_queue(
    user_id,
    node_id,
    detected_revision_id,
    reason,
    state,
    attempt_count,
    next_attempt_at,
    last_error_code,
    created_at,
    completed_at
)
SELECT
    user_id,
    node_id,
    detected_revision_id,
    reason,
    state,
    0,
    created_at,
    NULL,
    created_at,
    completed_at
FROM memory_repair_queue_v0063;

DROP TABLE memory_repair_queue_v0063;

CREATE INDEX idx_memory_repair_queue_due
    ON memory_repair_queue(state, next_attempt_at, created_at);

CREATE TABLE memory_catalog_reconcile_state (
    singleton_id INTEGER PRIMARY KEY CHECK (singleton_id = 1),
    last_user_id TEXT,
    last_node_id TEXT,
    updated_at TEXT NOT NULL,
    CHECK (
        (last_user_id IS NULL AND last_node_id IS NULL)
        OR (last_user_id IS NOT NULL AND last_node_id IS NOT NULL)
    )
);

INSERT INTO memory_catalog_reconcile_state(
    singleton_id, last_user_id, last_node_id, updated_at
) VALUES (1, NULL, NULL, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'));
