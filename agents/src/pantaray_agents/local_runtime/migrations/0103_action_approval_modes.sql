-- Per-Action approval mode override.
--
-- A row exists only while a conversation overrides the user-level default
-- (approval_preferences, scope_type='global'). The row is itself the durable
-- record of the user's consent for that Action, so it carries its own
-- timestamps and is deleted with the Action it belongs to.
CREATE TABLE IF NOT EXISTS action_approval_modes (
    action_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    approval_mode TEXT NOT NULL CHECK (
        approval_mode IN ('prompt_each_time', 'always_allow')
    ),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
    FOREIGN KEY (action_id) REFERENCES agent_actions(action_id) ON DELETE CASCADE
);
