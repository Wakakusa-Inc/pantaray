CREATE TABLE IF NOT EXISTS workspace_organizations (
    organization_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    display_name TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('active', 'inactive')) DEFAULT 'active',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
    UNIQUE (user_id, organization_id),
    UNIQUE (user_id, display_name)
);

CREATE TABLE IF NOT EXISTS workspace_projects (
    project_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    display_name TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('active', 'inactive')) DEFAULT 'active',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
    UNIQUE (user_id, project_id),
    UNIQUE (user_id, display_name)
);

CREATE TABLE IF NOT EXISTS workspace_project_organizations (
    user_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    organization_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (user_id, project_id, organization_id),
    FOREIGN KEY (user_id, project_id)
        REFERENCES workspace_projects(user_id, project_id) ON DELETE CASCADE,
    FOREIGN KEY (user_id, organization_id)
        REFERENCES workspace_organizations(user_id, organization_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS workspace_folders (
    folder_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    display_name TEXT NOT NULL,
    canonical_real_path TEXT NOT NULL,
    real_path TEXT NOT NULL,
    virtual_slug TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('active', 'inactive')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
    UNIQUE (user_id, folder_id),
    UNIQUE (user_id, virtual_slug),
    UNIQUE (user_id, canonical_real_path)
);

CREATE INDEX IF NOT EXISTS idx_workspace_folders_user_status
ON workspace_folders(user_id, status, display_name ASC);

CREATE TABLE IF NOT EXISTS workspace_folder_organizations (
    user_id TEXT NOT NULL,
    folder_id TEXT NOT NULL,
    organization_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (user_id, folder_id, organization_id),
    FOREIGN KEY (user_id, folder_id)
        REFERENCES workspace_folders(user_id, folder_id) ON DELETE CASCADE,
    FOREIGN KEY (user_id, organization_id)
        REFERENCES workspace_organizations(user_id, organization_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS workspace_folder_projects (
    user_id TEXT NOT NULL,
    folder_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (user_id, folder_id, project_id),
    FOREIGN KEY (user_id, folder_id)
        REFERENCES workspace_folders(user_id, folder_id) ON DELETE CASCADE,
    FOREIGN KEY (user_id, project_id)
        REFERENCES workspace_projects(user_id, project_id) ON DELETE CASCADE
);

DROP INDEX IF EXISTS idx_approval_sessions_action_status;
DROP INDEX IF EXISTS idx_approval_sessions_tool_invocation_status;
DROP INDEX IF EXISTS idx_approval_sessions_user_tool_request_status;

ALTER TABLE approval_sessions RENAME TO approval_sessions_legacy_v36;

CREATE TABLE approval_sessions (
    approval_session_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    action_id TEXT NOT NULL,
    workspace_id TEXT,
    tool_request_id TEXT NOT NULL,
    tool_invocation_id TEXT,
    tool_id TEXT NOT NULL,
    intent_class TEXT NOT NULL,
    approval_source TEXT NOT NULL CHECK (approval_source IN ('prompt', 'settings')),
    status TEXT NOT NULL CHECK (status IN ('pending', 'approved_once', 'denied')),
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

DROP INDEX IF EXISTS idx_command_invocation_audits_outcome_created;
DROP INDEX IF EXISTS idx_command_invocation_audits_exec_kind_created;

ALTER TABLE command_invocation_audits RENAME TO command_invocation_audits_legacy_v36;

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

DROP TABLE command_invocation_audits_legacy_v36;
DROP TABLE approval_sessions_legacy_v36;

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

CREATE TABLE IF NOT EXISTS workspace_manifests (
    manifest_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    action_id TEXT NOT NULL,
    execution_session_id TEXT,
    virtual_root_path TEXT NOT NULL,
    scratch_root_path TEXT NOT NULL,
    created_at TEXT NOT NULL,
    materialized_at TEXT,
    status TEXT NOT NULL CHECK (status IN ('materializing', 'ready', 'failed')),
    error_json TEXT CHECK (error_json IS NULL OR json_valid(error_json)),
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
    FOREIGN KEY (action_id) REFERENCES agent_actions(action_id) ON DELETE CASCADE,
    FOREIGN KEY (execution_session_id) REFERENCES execution_sessions(execution_session_id) ON DELETE SET NULL,
    UNIQUE (action_id)
);

CREATE INDEX IF NOT EXISTS idx_workspace_manifests_user_created
ON workspace_manifests(user_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_workspace_manifests_execution_session
ON workspace_manifests(execution_session_id);

CREATE TABLE IF NOT EXISTS workspace_manifest_mounts (
    mount_id TEXT PRIMARY KEY,
    manifest_id TEXT NOT NULL,
    source_type TEXT NOT NULL CHECK (source_type IN ('folder', 'scratch')),
    source_id TEXT,
    virtual_name TEXT NOT NULL,
    virtual_path TEXT NOT NULL,
    display_name TEXT NOT NULL,
    canonical_real_path TEXT NOT NULL,
    real_path TEXT NOT NULL,
    can_read INTEGER NOT NULL CHECK (can_read IN (0, 1)),
    can_apply_patch INTEGER NOT NULL CHECK (can_apply_patch IN (0, 1)),
    can_process_read INTEGER NOT NULL CHECK (can_process_read IN (0, 1)),
    can_process_write INTEGER NOT NULL CHECK (can_process_write IN (0, 1)),
    created_at TEXT NOT NULL,
    FOREIGN KEY (manifest_id) REFERENCES workspace_manifests(manifest_id) ON DELETE CASCADE,
    CHECK (
        (source_type = 'folder' AND source_id IS NOT NULL AND trim(source_id) <> '')
        OR (source_type = 'scratch' AND source_id = manifest_id)
    ),
    CHECK (virtual_name <> '' AND virtual_name NOT LIKE '%/%'),
    CHECK (virtual_path LIKE '/%' AND virtual_path NOT LIKE '%/../%'),
    UNIQUE (manifest_id, virtual_name),
    UNIQUE (manifest_id, virtual_path),
    UNIQUE (manifest_id, canonical_real_path)
);

CREATE INDEX IF NOT EXISTS idx_workspace_manifest_mounts_source
ON workspace_manifest_mounts(source_type, source_id);

DROP INDEX IF EXISTS idx_file_references_user_created;
DROP INDEX IF EXISTS idx_file_references_action;
DROP INDEX IF EXISTS idx_file_references_artifact;
DROP INDEX IF EXISTS idx_file_references_workspace_path;
DROP TABLE IF EXISTS file_references;

CREATE TABLE file_references (
    file_reference_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    action_id TEXT NOT NULL,
    manifest_id TEXT NOT NULL,
    mount_id TEXT,
    tool_invocation_id TEXT,
    virtual_path TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
    FOREIGN KEY (action_id) REFERENCES agent_actions(action_id) ON DELETE CASCADE,
    FOREIGN KEY (manifest_id) REFERENCES workspace_manifests(manifest_id) ON DELETE CASCADE,
    FOREIGN KEY (mount_id) REFERENCES workspace_manifest_mounts(mount_id) ON DELETE CASCADE,
    FOREIGN KEY (tool_invocation_id) REFERENCES tool_invocations(invocation_id) ON DELETE SET NULL,
    CHECK (virtual_path LIKE '/%' AND virtual_path NOT LIKE '%/../%'),
    UNIQUE (action_id, manifest_id, virtual_path)
);

CREATE INDEX idx_file_references_action_created
ON file_references(action_id, created_at ASC);

CREATE INDEX idx_file_references_manifest
ON file_references(manifest_id);

CREATE INDEX idx_file_references_tool_invocation
ON file_references(tool_invocation_id);
