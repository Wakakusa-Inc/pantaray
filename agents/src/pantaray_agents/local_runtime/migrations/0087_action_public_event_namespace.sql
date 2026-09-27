CREATE TABLE agent_process_events_v0087 (
    event_id TEXT PRIMARY KEY,
    suggestion_id TEXT,
    user_id TEXT NOT NULL,
    action_id TEXT,
    sequence INTEGER NOT NULL CHECK (sequence > 0),
    event_name TEXT NOT NULL CHECK (
        event_name IN (
            'process_started', 'suggestion_chunk',
            'suggestion_reaction_committed', 'action_requested',
            'action_resume_requested', 'action_summary',
            'action_message_accepted', 'action_message_adopted',
            'completion_chunk', 'process_paused',
            'process_completed', 'error'
        )
    ),
    payload TEXT NOT NULL CHECK (json_valid(payload)),
    created_at TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
    FOREIGN KEY (user_id, suggestion_id)
        REFERENCES agent_suggestions(user_id, suggestion_id) ON DELETE CASCADE,
    FOREIGN KEY (user_id, action_id)
        REFERENCES agent_actions(user_id, action_id) ON DELETE CASCADE,
    UNIQUE (suggestion_id, sequence),
    CHECK (suggestion_id IS NOT NULL OR action_id IS NOT NULL),
    CHECK (
        event_name NOT IN ('action_message_accepted', 'action_message_adopted')
        OR (suggestion_id IS NULL AND action_id IS NOT NULL)
    )
);

INSERT INTO agent_process_events_v0087(
    event_id, suggestion_id, user_id, action_id,
    sequence, event_name, payload, created_at
)
SELECT
    event_id, suggestion_id, user_id, action_id,
    sequence, event_name, payload, created_at
FROM agent_process_events
ORDER BY event_id;

DROP TABLE agent_process_events;
ALTER TABLE agent_process_events_v0087 RENAME TO agent_process_events;

CREATE INDEX idx_agent_process_events_suggestion_sequence
ON agent_process_events(suggestion_id, sequence ASC);

CREATE INDEX idx_agent_process_events_user_created
ON agent_process_events(user_id, created_at DESC);

CREATE UNIQUE INDEX uq_agent_process_events_action_sequence
ON agent_process_events(action_id, sequence)
WHERE action_id IS NOT NULL;
