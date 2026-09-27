CREATE TABLE command_network_preferences (
    user_id TEXT PRIMARY KEY REFERENCES users(user_id) ON DELETE CASCADE,
    command_network_enabled INTEGER NOT NULL CHECK (
        typeof(command_network_enabled) = 'integer'
        AND command_network_enabled IN (0, 1)
    ),
    updated_at TEXT NOT NULL
);
