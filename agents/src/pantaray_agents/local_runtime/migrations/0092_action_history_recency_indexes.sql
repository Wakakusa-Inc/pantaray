UPDATE agent_actions
SET created_at = strftime('%Y-%m-%dT%H:%M:%fZ', created_at),
    updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', updated_at);

UPDATE agent_suggestions
SET created_at = strftime('%Y-%m-%dT%H:%M:%fZ', created_at),
    updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', updated_at);

CREATE INDEX idx_agent_actions_user_history_recency
ON agent_actions(user_id, updated_at DESC, action_id);

CREATE INDEX idx_agent_suggestions_user_history_recency
ON agent_suggestions(user_id, updated_at DESC, suggestion_id);
