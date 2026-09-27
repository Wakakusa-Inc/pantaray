CREATE TABLE IF NOT EXISTS screen_captures (
    capture_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    storage_path TEXT NOT NULL,
    file_path TEXT NOT NULL,
    app_name TEXT,
    byte_size INTEGER NOT NULL CHECK (byte_size >= 0),
    mime_type TEXT NOT NULL,
    width_px INTEGER,
    height_px INTEGER,
    sha256 TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
    UNIQUE (storage_path)
);

CREATE INDEX IF NOT EXISTS idx_screen_captures_user_created
ON screen_captures(user_id, created_at DESC);

CREATE TABLE IF NOT EXISTS activity_logs (
    log_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    period_start TEXT NOT NULL,
    period_end TEXT NOT NULL,
    description TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('processing', 'success', 'error', 'canceled', 'timeout')),
    error TEXT CHECK (error IS NULL OR json_valid(error)),
    prompt_text TEXT,
    response_text TEXT,
    prompt_name TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    source_capture_paths TEXT CHECK (source_capture_paths IS NULL OR json_valid(source_capture_paths)),
    used_image_count INTEGER CHECK (used_image_count IS NULL OR used_image_count >= 0),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
    UNIQUE (user_id, period_start, period_end)
);

CREATE INDEX IF NOT EXISTS idx_activity_logs_user_period
ON activity_logs(user_id, period_start DESC);

CREATE TABLE IF NOT EXISTS activity_summaries (
    summary_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    summary_type TEXT NOT NULL CHECK (summary_type IN ('1h', '24h', '1w', '1m', '3m')),
    period_start TEXT NOT NULL,
    period_end TEXT NOT NULL,
    summary TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('processing', 'success', 'error', 'canceled', 'timeout')),
    error TEXT CHECK (error IS NULL OR json_valid(error)),
    prompt_text TEXT,
    response_text TEXT,
    prompt_name TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    source_ids TEXT CHECK (source_ids IS NULL OR json_valid(source_ids)),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
    UNIQUE (user_id, summary_type, period_start, period_end)
);

CREATE INDEX IF NOT EXISTS idx_activity_summaries_user_period
ON activity_summaries(user_id, summary_type, period_start DESC);
