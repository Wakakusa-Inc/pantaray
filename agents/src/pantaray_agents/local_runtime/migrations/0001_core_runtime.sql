PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS schema_versions (
    schema_version_id TEXT PRIMARY KEY,
    component TEXT NOT NULL,
    current_version INTEGER NOT NULL CHECK (current_version >= 0),
    applied_at TEXT NOT NULL,
    app_version TEXT NOT NULL,
    migration_name TEXT NOT NULL,
    checksum TEXT NOT NULL,
    UNIQUE (component)
);

CREATE TABLE IF NOT EXISTS migration_journal (
    migration_run_id TEXT PRIMARY KEY,
    migration_name TEXT NOT NULL,
    component TEXT NOT NULL,
    from_version INTEGER NOT NULL CHECK (from_version >= 0),
    to_version INTEGER NOT NULL CHECK (to_version >= from_version),
    started_at TEXT NOT NULL,
    completed_at TEXT,
    status TEXT NOT NULL CHECK (status IN ('running', 'completed', 'failed')),
    app_version TEXT NOT NULL,
    checksum TEXT NOT NULL,
    error_message TEXT
);

CREATE TABLE IF NOT EXISTS users (
    user_id TEXT PRIMARY KEY,
    ui_language TEXT NOT NULL,
    last_import_completed_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS processes (
    process_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (
        kind IN (
            'suggestion',
            'action',
            'insight',
            'fact',
            'activity_description',
            'activity_summary'
        )
    ),
    status TEXT NOT NULL CHECK (
        status IN ('enqueued', 'running', 'success', 'error', 'canceled', 'timeout', 'abandoned')
    ),
    suggestion_id TEXT,
    action_id TEXT,
    started_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    completed_at TEXT,
    heartbeat_at TEXT NOT NULL,
    terminal_event_id TEXT,
    acknowledged_at TEXT,
    current_job_id TEXT,
    next_event_seq INTEGER NOT NULL CHECK (next_event_seq >= 1),
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
);

CREATE INDEX idx_processes_user_updated ON processes(user_id, updated_at DESC);
CREATE INDEX idx_processes_kind_status ON processes(kind, status);
CREATE UNIQUE INDEX idx_processes_terminal_event_id ON processes(terminal_event_id) WHERE terminal_event_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS process_events (
    process_event_rowid INTEGER PRIMARY KEY AUTOINCREMENT,
    process_id TEXT NOT NULL,
    event_seq INTEGER NOT NULL CHECK (event_seq >= 1),
    event_id TEXT NOT NULL,
    event_name TEXT NOT NULL,
    payload_json TEXT NOT NULL CHECK (json_valid(payload_json)),
    chunk_index INTEGER,
    created_at TEXT NOT NULL,
    FOREIGN KEY (process_id) REFERENCES processes(process_id) ON DELETE CASCADE,
    UNIQUE (process_id, event_seq),
    UNIQUE (process_id, event_id)
);

CREATE INDEX idx_process_events_process_created ON process_events(process_id, created_at ASC);
CREATE INDEX idx_process_events_name_created ON process_events(event_name, created_at DESC);

CREATE TABLE IF NOT EXISTS jobs (
    job_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    job_type TEXT NOT NULL,
    process_id TEXT,
    status TEXT NOT NULL CHECK (
        status IN ('queued', 'running', 'retryable_error', 'blocked', 'completed', 'abandoned', 'canceled')
    ),
    attempt INTEGER NOT NULL DEFAULT 0 CHECK (attempt >= 0),
    claimed_by TEXT,
    claimed_at TEXT,
    heartbeat_at TEXT,
    cancel_requested_at TEXT,
    timeout_at TEXT,
    next_retry_at TEXT,
    scheduled_at TEXT NOT NULL,
    started_at TEXT,
    completed_at TEXT,
    error_code TEXT,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
    FOREIGN KEY (process_id) REFERENCES processes(process_id) ON DELETE SET NULL
);

CREATE INDEX idx_jobs_status_schedule ON jobs(status, scheduled_at ASC);
CREATE INDEX idx_jobs_process_id ON jobs(process_id);
CREATE INDEX idx_jobs_retry ON jobs(status, next_retry_at ASC) WHERE status = 'retryable_error';

CREATE TABLE IF NOT EXISTS job_attempts (
    attempt_id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL,
    attempt_number INTEGER NOT NULL CHECK (attempt_number >= 1),
    started_at TEXT NOT NULL,
    completed_at TEXT,
    status TEXT NOT NULL CHECK (status IN ('running', 'completed', 'failed', 'canceled')),
    error_code TEXT,
    error_message TEXT,
    FOREIGN KEY (job_id) REFERENCES jobs(job_id) ON DELETE CASCADE,
    UNIQUE (job_id, attempt_number)
);

CREATE INDEX idx_job_attempts_job ON job_attempts(job_id, attempt_number ASC);

CREATE TABLE IF NOT EXISTS runtime_recovery_runs (
    recovery_run_id TEXT PRIMARY KEY,
    started_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    status TEXT NOT NULL,
    note TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS job_payloads (
    job_id TEXT PRIMARY KEY,
    payload_json TEXT NOT NULL CHECK (json_valid(payload_json)),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    FOREIGN KEY (job_id) REFERENCES jobs(job_id) ON DELETE CASCADE
);
