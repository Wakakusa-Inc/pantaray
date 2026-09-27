CREATE TABLE IF NOT EXISTS scheduler_jobs (
    job_name TEXT PRIMARY KEY,
    job_kind TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('active', 'paused', 'blocked')),
    cursor_value TEXT,
    next_run_after TEXT,
    last_started_at TEXT,
    last_completed_at TEXT,
    last_success_at TEXT,
    consecutive_failures INTEGER NOT NULL DEFAULT 0 CHECK (consecutive_failures >= 0)
);

CREATE TABLE IF NOT EXISTS scheduler_job_runs (
    run_id TEXT PRIMARY KEY,
    job_name TEXT NOT NULL,
    logical_window_start TEXT NOT NULL,
    logical_window_end TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('queued', 'running', 'completed', 'failed', 'skipped')),
    attempt INTEGER NOT NULL DEFAULT 1 CHECK (attempt >= 1),
    error_code TEXT,
    error_details_json TEXT CHECK (error_details_json IS NULL OR json_valid(error_details_json)),
    enqueued_at TEXT NOT NULL,
    started_at TEXT,
    completed_at TEXT,
    FOREIGN KEY (job_name) REFERENCES scheduler_jobs(job_name) ON DELETE CASCADE
);

CREATE INDEX idx_scheduler_job_runs_job_window ON scheduler_job_runs(job_name, logical_window_start DESC);

CREATE TABLE IF NOT EXISTS approval_preferences (
    preference_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    scope_type TEXT NOT NULL CHECK (scope_type IN ('global', 'workspace')),
    scope_ref TEXT,
    approval_mode TEXT NOT NULL CHECK (approval_mode IN ('prompt_each_time', 'always_allow')),
    applies_to_json TEXT NOT NULL CHECK (json_valid(applies_to_json)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    updated_by TEXT NOT NULL CHECK (updated_by = 'user'),
    revoked_at TEXT,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
    FOREIGN KEY (scope_ref) REFERENCES workspaces(workspace_id) ON DELETE CASCADE,
    CHECK (
        (scope_type = 'global' AND scope_ref IS NULL)
        OR (scope_type = 'workspace' AND scope_ref IS NOT NULL)
    )
);

CREATE INDEX idx_approval_preferences_user_scope ON approval_preferences(user_id, scope_type, scope_ref, updated_at DESC);

CREATE TABLE IF NOT EXISTS capability_grants (
    grant_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    preference_id TEXT,
    capability TEXT NOT NULL,
    scope_type TEXT NOT NULL,
    scope_ref TEXT,
    grant_source TEXT NOT NULL CHECK (grant_source IN ('settings', 'prompt')),
    granted_at TEXT NOT NULL,
    granted_by TEXT NOT NULL CHECK (granted_by = 'user'),
    revoked_at TEXT,
    revocation_reason TEXT,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
    FOREIGN KEY (preference_id) REFERENCES approval_preferences(preference_id) ON DELETE SET NULL
);

CREATE INDEX idx_capability_grants_user_capability ON capability_grants(user_id, capability, granted_at DESC);

CREATE TABLE IF NOT EXISTS approval_sessions (
    approval_session_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    action_id TEXT NOT NULL,
    workspace_id TEXT,
    tool_request_id TEXT NOT NULL,
    tool_invocation_id TEXT,
    tool_id TEXT NOT NULL,
    intent_class TEXT NOT NULL,
    approval_source TEXT NOT NULL CHECK (approval_source IN ('prompt', 'settings')),
    status TEXT NOT NULL CHECK (status IN ('pending', 'approved_once', 'approved_and_persisted', 'denied')),
    approved_capabilities_json TEXT NOT NULL CHECK (json_valid(approved_capabilities_json)),
    command_summary_json TEXT NOT NULL CHECK (json_valid(command_summary_json)),
    requested_at TEXT NOT NULL,
    decided_at TEXT,
    created_at TEXT NOT NULL,
    claimed_at TEXT,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
    FOREIGN KEY (action_id) REFERENCES agent_actions(action_id) ON DELETE CASCADE,
    FOREIGN KEY (workspace_id) REFERENCES workspaces(workspace_id) ON DELETE SET NULL,
    FOREIGN KEY (tool_invocation_id) REFERENCES tool_invocations(invocation_id) ON DELETE SET NULL,
    CHECK (
        (status = 'pending' AND decided_at IS NULL)
        OR (status != 'pending' AND decided_at IS NOT NULL)
    ),
    CHECK (claimed_at IS NULL OR tool_invocation_id IS NOT NULL),
    CHECK (
        status NOT IN ('pending', 'denied')
        OR (claimed_at IS NULL AND tool_invocation_id IS NULL)
    ),
    UNIQUE (user_id, tool_request_id)
);

CREATE INDEX idx_approval_sessions_action_status ON approval_sessions(action_id, status, requested_at DESC);
CREATE INDEX idx_approval_sessions_tool_invocation_status ON approval_sessions(tool_invocation_id, status, requested_at DESC);
CREATE INDEX idx_approval_sessions_user_tool_request_status ON approval_sessions(user_id, tool_request_id, status, requested_at DESC);

CREATE TABLE IF NOT EXISTS artifact_manifest (
    artifact_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    artifact_kind TEXT NOT NULL,
    root_path TEXT NOT NULL,
    content_sha256 TEXT NOT NULL,
    byte_size INTEGER NOT NULL CHECK (byte_size >= 0),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    last_verified_at TEXT,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS file_references (
    file_ref_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    action_id TEXT,
    artifact_id TEXT,
    workspace_id TEXT,
    reference_kind TEXT NOT NULL CHECK (reference_kind IN ('managed_artifact', 'workspace_file')),
    relative_path TEXT NOT NULL,
    display_name TEXT NOT NULL,
    mime_type TEXT,
    open_target TEXT NOT NULL CHECK (open_target IN ('reveal_in_finder', 'open_in_place', 'open_artifact')),
    is_user_visible INTEGER NOT NULL CHECK (is_user_visible IN (0, 1)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
    FOREIGN KEY (action_id) REFERENCES agent_actions(action_id) ON DELETE SET NULL,
    FOREIGN KEY (artifact_id) REFERENCES artifact_manifest(artifact_id) ON DELETE SET NULL,
    FOREIGN KEY (workspace_id) REFERENCES workspaces(workspace_id) ON DELETE SET NULL,
    CHECK (
        (reference_kind = 'managed_artifact' AND artifact_id IS NOT NULL)
        OR (reference_kind = 'workspace_file' AND workspace_id IS NOT NULL)
    )
);

CREATE INDEX idx_file_references_user_created ON file_references(user_id, created_at DESC);
CREATE INDEX idx_file_references_action ON file_references(action_id, created_at ASC);
CREATE INDEX idx_file_references_artifact ON file_references(artifact_id);
CREATE INDEX idx_file_references_workspace_path ON file_references(workspace_id, relative_path);

CREATE TABLE IF NOT EXISTS retention_jobs (
    retention_job_id TEXT PRIMARY KEY,
    job_name TEXT NOT NULL,
    scope TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('active', 'paused', 'failed')),
    last_run_at TEXT,
    last_deleted_count INTEGER NOT NULL DEFAULT 0 CHECK (last_deleted_count >= 0),
    last_error_code TEXT,
    last_error_message TEXT
);

CREATE TABLE IF NOT EXISTS fts_jobs (
    fts_job_id TEXT PRIMARY KEY,
    target_table TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('queued', 'running', 'completed', 'failed')),
    enqueued_at TEXT NOT NULL,
    started_at TEXT,
    completed_at TEXT,
    last_indexed_cursor TEXT,
    error_message TEXT
);

CREATE TABLE IF NOT EXISTS import_runs (
    import_run_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('running', 'completed', 'failed')),
    started_at TEXT NOT NULL,
    completed_at TEXT,
    requested_by TEXT NOT NULL,
    force_reindex INTEGER NOT NULL CHECK (force_reindex IN (0, 1)),
    error_code TEXT,
    error_message TEXT,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
);

CREATE INDEX idx_import_runs_user_started ON import_runs(user_id, started_at DESC);

CREATE TABLE IF NOT EXISTS import_run_sources (
    import_run_source_id TEXT PRIMARY KEY,
    import_run_id TEXT NOT NULL,
    source_name TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('running', 'completed', 'failed', 'skipped')),
    watermark_value TEXT,
    imported_count INTEGER NOT NULL DEFAULT 0 CHECK (imported_count >= 0),
    skipped_count INTEGER NOT NULL DEFAULT 0 CHECK (skipped_count >= 0),
    artifact_repaired_count INTEGER NOT NULL DEFAULT 0 CHECK (artifact_repaired_count >= 0),
    started_at TEXT NOT NULL,
    completed_at TEXT,
    error_code TEXT,
    error_message TEXT,
    FOREIGN KEY (import_run_id) REFERENCES import_runs(import_run_id) ON DELETE CASCADE,
    UNIQUE (import_run_id, source_name)
);

CREATE TABLE IF NOT EXISTS feature_readiness (
    user_id TEXT NOT NULL,
    feature_key TEXT NOT NULL CHECK (
        feature_key IN (
            'live_capture',
            'live_actions',
            'workspace_editing',
            'history_timeline',
            'history_search',
            'insight_memory',
            'artifact_store'
        )
    ),
    state TEXT NOT NULL CHECK (state IN ('ready', 'degraded', 'blocked')),
    reason_code TEXT,
    watermark_json TEXT CHECK (watermark_json IS NULL OR json_valid(watermark_json)),
    updated_at TEXT NOT NULL,
    PRIMARY KEY (user_id, feature_key),
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
);
