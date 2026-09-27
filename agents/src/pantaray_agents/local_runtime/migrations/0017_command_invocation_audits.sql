CREATE TABLE IF NOT EXISTS command_invocation_audits (
    invocation_id TEXT PRIMARY KEY,
    approval_session_id TEXT NOT NULL,
    execution_kind TEXT NOT NULL CHECK (
        execution_kind IN ('agent_generated', 'workspace_command')
    ),
    executable_source_kind TEXT NOT NULL CHECK (
        executable_source_kind IN (
            'app_runtime_python',
            'workspace_root_executable'
        )
    ),
    resolved_executable_path TEXT NOT NULL,
    terminal_outcome TEXT NOT NULL CHECK (
        terminal_outcome IN (
            'exited',
            'signaled',
            'timed_out',
            'canceled',
            'sandbox_violation',
            'spawn_failed',
            'budget_exceeded',
            'broker_failed'
        )
    ),
    exit_code INTEGER,
    signal INTEGER,
    stdout_bytes INTEGER NOT NULL DEFAULT 0 CHECK (stdout_bytes >= 0),
    stderr_bytes INTEGER NOT NULL DEFAULT 0 CHECK (stderr_bytes >= 0),
    stdout_max_bytes INTEGER NOT NULL CHECK (stdout_max_bytes > 0),
    stderr_max_bytes INTEGER NOT NULL CHECK (stderr_max_bytes > 0),
    temp_storage_limit_bytes INTEGER NOT NULL CHECK (temp_storage_limit_bytes > 0),
    child_count_limit INTEGER NOT NULL CHECK (child_count_limit > 0),
    open_file_lease_limit INTEGER NOT NULL CHECK (open_file_lease_limit > 0),
    budget_exceeded_kind TEXT CHECK (
        budget_exceeded_kind IS NULL
        OR budget_exceeded_kind IN (
            'stdout_limit',
            'stderr_limit',
            'temp_storage_limit',
            'child_count_limit',
            'open_file_lease_limit'
        )
    ),
    sandbox_violation_kind TEXT CHECK (
        sandbox_violation_kind IS NULL
        OR sandbox_violation_kind IN (
            'path_escape',
            'write_denied',
            'exec_denied',
            'network_denied',
            'unknown'
        )
    ),
    sandbox_violation_summary TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (invocation_id) REFERENCES tool_invocations(invocation_id) ON DELETE CASCADE,
    FOREIGN KEY (approval_session_id) REFERENCES approval_sessions(approval_session_id) ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS idx_command_invocation_audits_outcome_created
ON command_invocation_audits(terminal_outcome, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_command_invocation_audits_exec_kind_created
ON command_invocation_audits(execution_kind, created_at DESC);
