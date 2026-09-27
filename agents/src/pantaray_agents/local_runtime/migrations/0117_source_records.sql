-- Verbatim evidence, appended with the activity log and its read cursor.
-- Records share the producing log's lifetime. Project attribution belongs to a
-- later evidence-based decision, not this table.
CREATE TABLE source_records (
    record_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    run_id TEXT NOT NULL REFERENCES activity_logs(log_id) ON DELETE CASCADE,
    event_id TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    app_name TEXT,
    bundle_id TEXT,
    window_title TEXT,
    source TEXT NOT NULL,
    speaker TEXT NOT NULL,
    shown_time TEXT NOT NULL,
    quote TEXT NOT NULL CHECK (length(quote) > 0),
    created_at TEXT NOT NULL
);

-- Records are read back over a period of the user's own history; the run that
-- produced them is reachable through `activity_logs` when it is needed.
CREATE INDEX idx_source_records_user_observed
ON source_records(user_id, observed_at);
