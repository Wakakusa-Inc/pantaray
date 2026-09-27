PRAGMA foreign_keys = ON;

UPDATE tool_invocations
SET step_id = NULL
WHERE step_id IN (
    SELECT step_id
    FROM agent_action_steps
    WHERE short_step_id LIKE 'synthetic-%-TOOL'
);

DELETE FROM agent_action_steps
WHERE short_step_id LIKE 'synthetic-%-TOOL';

DROP INDEX IF EXISTS idx_approval_sessions_action_status;
DROP INDEX IF EXISTS idx_approval_sessions_tool_invocation_status;
DROP INDEX IF EXISTS idx_approval_sessions_user_tool_request_status;

PRAGMA legacy_alter_table = ON;

ALTER TABLE approval_sessions RENAME TO approval_sessions_legacy_v40;

CREATE TABLE approval_sessions (
    approval_session_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    action_id TEXT NOT NULL,
    manifest_id TEXT,
    tool_request_id TEXT NOT NULL,
    tool_invocation_id TEXT,
    tool_id TEXT NOT NULL,
    intent_class TEXT NOT NULL,
    approval_source TEXT NOT NULL CHECK (approval_source IN ('prompt', 'settings')),
    status TEXT NOT NULL CHECK (
        status IN ('pending', 'approved_once', 'denied', 'interrupted')
    ),
    approved_capabilities_json TEXT NOT NULL CHECK (json_valid(approved_capabilities_json)),
    command_summary_json TEXT NOT NULL CHECK (json_valid(command_summary_json)),
    requested_at TEXT NOT NULL,
    decided_at TEXT,
    created_at TEXT NOT NULL,
    claimed_at TEXT,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
    FOREIGN KEY (action_id) REFERENCES agent_actions(action_id) ON DELETE CASCADE,
    FOREIGN KEY (manifest_id) REFERENCES workspace_manifests(manifest_id) ON DELETE SET NULL,
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

INSERT INTO approval_sessions(
    approval_session_id,
    user_id,
    action_id,
    manifest_id,
    tool_request_id,
    tool_invocation_id,
    tool_id,
    intent_class,
    approval_source,
    status,
    approved_capabilities_json,
    command_summary_json,
    requested_at,
    decided_at,
    created_at,
    claimed_at
)
SELECT
    approval_session_id,
    user_id,
    action_id,
    manifest_id,
    tool_request_id,
    tool_invocation_id,
    tool_id,
    intent_class,
    approval_source,
    status,
    approved_capabilities_json,
    command_summary_json,
    requested_at,
    decided_at,
    created_at,
    claimed_at
FROM approval_sessions_legacy_v40;

DROP INDEX IF EXISTS idx_command_invocation_audits_outcome_created;
DROP INDEX IF EXISTS idx_command_invocation_audits_exec_kind_created;

ALTER TABLE command_invocation_audits RENAME TO command_invocation_audits_legacy_v40;

CREATE TABLE command_invocation_audits (
    invocation_id TEXT PRIMARY KEY,
    approval_session_id TEXT,
    execution_kind TEXT NOT NULL CHECK (
        execution_kind IN ('agent_generated', 'workspace_command')
    ),
    executable_source_kind TEXT NOT NULL CHECK (
        executable_source_kind IN (
            'app_runtime_python',
            'trusted_system_executable',
            'workspace_managed_executable'
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

INSERT INTO command_invocation_audits(
    invocation_id,
    approval_session_id,
    execution_kind,
    executable_source_kind,
    resolved_executable_path,
    terminal_outcome,
    exit_code,
    signal,
    stdout_bytes,
    stderr_bytes,
    stdout_max_bytes,
    stderr_max_bytes,
    temp_storage_limit_bytes,
    child_count_limit,
    open_file_lease_limit,
    budget_exceeded_kind,
    sandbox_violation_kind,
    sandbox_violation_summary,
    created_at,
    updated_at
)
SELECT
    invocation_id,
    approval_session_id,
    execution_kind,
    executable_source_kind,
    resolved_executable_path,
    terminal_outcome,
    exit_code,
    signal,
    stdout_bytes,
    stderr_bytes,
    stdout_max_bytes,
    stderr_max_bytes,
    temp_storage_limit_bytes,
    child_count_limit,
    open_file_lease_limit,
    budget_exceeded_kind,
    sandbox_violation_kind,
    sandbox_violation_summary,
    created_at,
    updated_at
FROM command_invocation_audits_legacy_v40;

DROP TABLE command_invocation_audits_legacy_v40;

DROP TABLE approval_sessions_legacy_v40;

PRAGMA legacy_alter_table = OFF;

CREATE INDEX idx_approval_sessions_action_status
ON approval_sessions(action_id, status, requested_at DESC);

CREATE INDEX idx_approval_sessions_tool_invocation_status
ON approval_sessions(tool_invocation_id, status, requested_at DESC);

CREATE INDEX idx_approval_sessions_user_tool_request_status
ON approval_sessions(user_id, tool_request_id, status, requested_at DESC);

CREATE INDEX idx_command_invocation_audits_outcome_created
ON command_invocation_audits(terminal_outcome, created_at DESC);

CREATE INDEX idx_command_invocation_audits_exec_kind_created
ON command_invocation_audits(execution_kind, created_at DESC);
