PRAGMA foreign_keys = OFF;

CREATE TABLE agent_process_events_new (
    event_id TEXT PRIMARY KEY,
    suggestion_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    action_id TEXT,
    sequence INTEGER NOT NULL CHECK (sequence > 0),
    event_name TEXT NOT NULL CHECK (
        event_name IN (
            'process_started',
            'suggestion_chunk',
            'suggestion_reaction_committed',
            'action_requested',
            'action_resume_requested',
            'action_summary',
            'completion_chunk',
            'process_paused',
            'process_completed',
            'error'
        )
    ),
    payload TEXT NOT NULL CHECK (json_valid(payload)),
    created_at TEXT NOT NULL,
    FOREIGN KEY (suggestion_id) REFERENCES agent_suggestions(suggestion_id) ON DELETE CASCADE,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
    FOREIGN KEY (action_id) REFERENCES agent_actions(action_id) ON DELETE CASCADE,
    UNIQUE (suggestion_id, sequence)
);

INSERT INTO agent_process_events_new (
    event_id,
    suggestion_id,
    user_id,
    action_id,
    sequence,
    event_name,
    payload,
    created_at
)
SELECT
    event_id,
    suggestion_id,
    user_id,
    action_id,
    sequence,
    event_name,
    payload,
    created_at
FROM agent_process_events;

DROP TABLE agent_process_events;
ALTER TABLE agent_process_events_new RENAME TO agent_process_events;

CREATE INDEX idx_agent_process_events_suggestion_sequence
ON agent_process_events(suggestion_id, sequence ASC);

CREATE INDEX idx_agent_process_events_action_sequence
ON agent_process_events(action_id, sequence ASC)
WHERE action_id IS NOT NULL;

CREATE INDEX idx_agent_process_events_user_created
ON agent_process_events(user_id, created_at DESC);

PRAGMA foreign_keys = ON;
