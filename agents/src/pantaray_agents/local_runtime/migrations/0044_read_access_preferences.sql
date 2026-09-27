CREATE TABLE read_access_preferences (
    user_id TEXT PRIMARY KEY,
    read_access_scope TEXT NOT NULL CHECK (
        read_access_scope IN ('workspace', 'full_access')
    ),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    updated_by TEXT NOT NULL CHECK (updated_by = 'user'),
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
);

INSERT INTO read_access_preferences(
    user_id,
    read_access_scope,
    created_at,
    updated_at,
    updated_by
)
SELECT
    user_id,
    'workspace',
    updated_at,
    updated_at,
    'user'
FROM users;
