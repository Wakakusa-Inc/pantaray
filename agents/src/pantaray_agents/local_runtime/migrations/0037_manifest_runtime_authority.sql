PRAGMA defer_foreign_keys = ON;
DROP TRIGGER IF EXISTS reject_tool_runtime_resource_socket_insert;
DROP TRIGGER IF EXISTS reject_tool_runtime_resource_socket_update;
DROP INDEX IF EXISTS idx_command_invocation_audits_outcome_created;
DROP INDEX IF EXISTS idx_command_invocation_audits_exec_kind_created;
DROP INDEX IF EXISTS idx_approval_sessions_action_status;
DROP INDEX IF EXISTS idx_approval_sessions_tool_invocation_status;
DROP INDEX IF EXISTS idx_approval_sessions_user_tool_request_status;
DROP INDEX IF EXISTS idx_tool_runtime_resource_events_resource_created;
DROP INDEX IF EXISTS idx_tool_runtime_resource_events_invocation_created;
DROP INDEX IF EXISTS idx_tool_runtime_resources_status_created;
DROP INDEX IF EXISTS idx_tool_runtime_resources_invocation_status;
DROP INDEX IF EXISTS idx_tool_runtime_resources_action_status;
DROP INDEX IF EXISTS idx_tool_outputs_invocation_created;
DROP INDEX IF EXISTS idx_tool_invocations_tool_request;
DROP INDEX IF EXISTS idx_tool_invocations_step;
DROP INDEX IF EXISTS idx_tool_invocations_action_started;
DROP INDEX IF EXISTS idx_execution_sessions_action_started;
DROP INDEX IF EXISTS idx_file_references_tool_invocation;
DROP INDEX IF EXISTS idx_file_references_manifest;
DROP INDEX IF EXISTS idx_file_references_action_created;
DROP INDEX IF EXISTS idx_workspace_manifest_mounts_source;
DROP INDEX IF EXISTS idx_workspace_manifests_execution_session;
DROP INDEX IF EXISTS idx_capability_grants_user_capability;
DROP INDEX IF EXISTS idx_approval_preferences_user_scope;
ALTER TABLE capability_grants RENAME TO capability_grants_legacy_v37;
ALTER TABLE approval_preferences RENAME TO approval_preferences_legacy_v37;
ALTER TABLE file_references RENAME TO file_references_legacy_v37;
ALTER TABLE workspace_manifest_mounts RENAME TO workspace_manifest_mounts_legacy_v37;
ALTER TABLE workspace_manifests RENAME TO workspace_manifests_legacy_v37;
ALTER TABLE command_invocation_audits RENAME TO command_invocation_audits_legacy_v37;
ALTER TABLE approval_sessions RENAME TO approval_sessions_legacy_v37;
ALTER TABLE tool_runtime_resource_events RENAME TO tool_runtime_resource_events_legacy_v37;
ALTER TABLE tool_runtime_resources RENAME TO tool_runtime_resources_legacy_v37;
ALTER TABLE tool_outputs RENAME TO tool_outputs_legacy_v37;
ALTER TABLE tool_invocations RENAME TO tool_invocations_legacy_v37;
ALTER TABLE execution_sessions RENAME TO execution_sessions_legacy_v37;
CREATE TABLE approval_preferences (
    preference_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    scope_type TEXT NOT NULL CHECK (scope_type = 'global'),
    scope_ref TEXT CHECK (scope_ref IS NULL),
    approval_mode TEXT NOT NULL CHECK (approval_mode IN ('prompt_each_time', 'always_allow')),
    applies_to_json TEXT NOT NULL CHECK (json_valid(applies_to_json)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    updated_by TEXT NOT NULL CHECK (updated_by = 'user'),
    revoked_at TEXT,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
    CHECK (scope_type = 'global' AND scope_ref IS NULL)
);
CREATE INDEX idx_approval_preferences_user_scope
ON approval_preferences(user_id, scope_type, scope_ref, updated_at DESC);
CREATE TABLE capability_grants (
    grant_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    preference_id TEXT,
    capability TEXT NOT NULL,
    scope_type TEXT NOT NULL CHECK (scope_type = 'global'),
    scope_ref TEXT CHECK (scope_ref IS NULL),
    grant_source TEXT NOT NULL CHECK (grant_source IN ('settings', 'prompt')),
    granted_at TEXT NOT NULL,
    granted_by TEXT NOT NULL CHECK (granted_by = 'user'),
    revoked_at TEXT,
    revocation_reason TEXT,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
    FOREIGN KEY (preference_id) REFERENCES approval_preferences(preference_id) ON DELETE SET NULL,
    CHECK (scope_type = 'global' AND scope_ref IS NULL)
);
CREATE INDEX idx_capability_grants_user_capability
ON capability_grants(user_id, capability, granted_at DESC);
INSERT INTO approval_preferences(
    preference_id,
    user_id,
    scope_type,
    scope_ref,
    approval_mode,
    applies_to_json,
    created_at,
    updated_at,
    updated_by,
    revoked_at
)
SELECT
    preference_id,
    user_id,
    scope_type,
    scope_ref,
    approval_mode,
    applies_to_json,
    created_at,
    updated_at,
    updated_by,
    revoked_at
FROM approval_preferences_legacy_v37
WHERE scope_type = 'global' AND scope_ref IS NULL;
INSERT INTO capability_grants(
    grant_id,
    user_id,
    preference_id,
    capability,
    scope_type,
    scope_ref,
    grant_source,
    granted_at,
    granted_by,
    revoked_at,
    revocation_reason
)
SELECT
    grant_id,
    user_id,
    preference_id,
    capability,
    scope_type,
    scope_ref,
    grant_source,
    granted_at,
    granted_by,
    revoked_at,
    revocation_reason
FROM capability_grants_legacy_v37
WHERE scope_type = 'global'
  AND scope_ref IS NULL
  AND (
      preference_id IS NULL
      OR preference_id IN (
          SELECT preference_id
          FROM approval_preferences
      )
  );
CREATE TABLE execution_sessions (
    execution_session_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    action_id TEXT,
    parent_execution_session_id TEXT,
    exec_mode TEXT NOT NULL CHECK (
        exec_mode IN ('brokered_file_ops', 'workspace_command')
    ),
    cwd_path TEXT NOT NULL,
    action_temp_dir TEXT,
    app_runtime_python TEXT,
    network_policy TEXT NOT NULL,
    capability_snapshot_json TEXT NOT NULL CHECK (json_valid(capability_snapshot_json)),
    tool_allowlist_json TEXT CHECK (
        tool_allowlist_json IS NULL OR json_valid(tool_allowlist_json)
    ),
    status TEXT NOT NULL CHECK (
        status IN ('running', 'completed', 'failed', 'canceled', 'expired')
    ),
    started_at TEXT NOT NULL,
    completed_at TEXT,
    expires_at TEXT,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
    FOREIGN KEY (action_id) REFERENCES agent_actions(action_id) ON DELETE CASCADE,
    FOREIGN KEY (parent_execution_session_id)
        REFERENCES execution_sessions(execution_session_id) ON DELETE SET NULL
);
CREATE TABLE workspace_manifests (
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
    FOREIGN KEY (execution_session_id)
        REFERENCES execution_sessions(execution_session_id) ON DELETE SET NULL,
    UNIQUE (action_id)
);
CREATE INDEX idx_workspace_manifests_execution_session ON workspace_manifests(execution_session_id);
CREATE TABLE workspace_manifest_mounts (
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
CREATE INDEX idx_workspace_manifest_mounts_source ON workspace_manifest_mounts(source_type, source_id);
CREATE TABLE tool_invocations (
    invocation_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    action_id TEXT NOT NULL,
    step_id TEXT,
    tool_id TEXT NOT NULL,
    manifest_id TEXT,
    execution_session_id TEXT NOT NULL,
    cwd TEXT,
    timeout_ms INTEGER CHECK (timeout_ms IS NULL OR timeout_ms > 0),
    intent_class TEXT NOT NULL CHECK (
        intent_class IN (
            'read_only',
            'surgical_edit',
            'bulk_edit',
            'process_exec_local',
            'dependency_install',
            'dependency_update',
            'network_access',
            'automation_control',
            'screen_capture'
        )
    ),
    network_policy TEXT,
    command_summary_json TEXT CHECK (
        command_summary_json IS NULL OR json_valid(command_summary_json)
    ),
    capability_snapshot_json TEXT CHECK (
        capability_snapshot_json IS NULL OR json_valid(capability_snapshot_json)
    ),
    tool_request_id TEXT,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    status TEXT NOT NULL CHECK (
        status IN ('queued', 'running', 'completed', 'failed', 'canceled', 'timed_out')
    ),
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
    FOREIGN KEY (action_id) REFERENCES agent_actions(action_id) ON DELETE CASCADE,
    FOREIGN KEY (step_id) REFERENCES agent_action_steps(step_id) ON DELETE SET NULL,
    FOREIGN KEY (tool_id) REFERENCES tool_definitions(tool_id) ON DELETE RESTRICT,
    FOREIGN KEY (manifest_id) REFERENCES workspace_manifests(manifest_id) ON DELETE SET NULL,
    FOREIGN KEY (execution_session_id)
        REFERENCES execution_sessions(execution_session_id) ON DELETE CASCADE
);
CREATE INDEX idx_tool_invocations_action_started ON tool_invocations(action_id, started_at ASC);
CREATE INDEX idx_tool_invocations_step ON tool_invocations(step_id);
CREATE INDEX idx_tool_invocations_tool_request ON tool_invocations(tool_request_id);
CREATE TABLE tool_outputs (
    output_id TEXT PRIMARY KEY,
    invocation_id TEXT NOT NULL,
    search_text TEXT,
    stdout_text TEXT,
    stderr_text TEXT,
    output_json TEXT CHECK (output_json IS NULL OR json_valid(output_json)),
    redaction_applied INTEGER NOT NULL CHECK (redaction_applied IN (0, 1)),
    created_at TEXT NOT NULL,
    FOREIGN KEY (invocation_id) REFERENCES tool_invocations(invocation_id) ON DELETE CASCADE
);
CREATE INDEX idx_tool_outputs_invocation_created ON tool_outputs(invocation_id, created_at ASC);
CREATE TABLE tool_runtime_resources (
    resource_id TEXT PRIMARY KEY,
    execution_session_id TEXT NOT NULL,
    tool_invocation_id TEXT,
    action_id TEXT,
    resource_kind TEXT NOT NULL CHECK (
        resource_kind IN ('process_group', 'temp_file', 'temp_dir', 'socket', 'lock')
    ),
    status TEXT NOT NULL CHECK (
        status IN ('active', 'cleaned', 'cleanup_failed', 'abandoned')
    ),
    pid INTEGER,
    pgid INTEGER,
    process_start_signature TEXT,
    resource_path TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    cleaned_at TEXT,
    cleanup_error TEXT,
    cleanup_attempts INTEGER NOT NULL DEFAULT 0 CHECK (cleanup_attempts >= 0),
    lock_id TEXT,
    FOREIGN KEY (execution_session_id)
        REFERENCES execution_sessions(execution_session_id) ON DELETE CASCADE,
    FOREIGN KEY (tool_invocation_id)
        REFERENCES tool_invocations(invocation_id) ON DELETE SET NULL
);
CREATE INDEX idx_tool_runtime_resources_action_status ON tool_runtime_resources(action_id, status, created_at ASC);
CREATE INDEX idx_tool_runtime_resources_invocation_status ON tool_runtime_resources(tool_invocation_id, status, created_at ASC);
CREATE INDEX idx_tool_runtime_resources_status_created ON tool_runtime_resources(status, created_at ASC);
CREATE TRIGGER reject_tool_runtime_resource_socket_insert
BEFORE INSERT ON tool_runtime_resources
FOR EACH ROW
WHEN NEW.resource_kind = 'socket'
BEGIN
    SELECT RAISE(ABORT, 'socket resources are outside the current local runtime transport scope');
END;
CREATE TRIGGER reject_tool_runtime_resource_socket_update
BEFORE UPDATE OF resource_kind ON tool_runtime_resources
FOR EACH ROW
WHEN NEW.resource_kind = 'socket'
BEGIN
    SELECT RAISE(ABORT, 'socket resources are outside the current local runtime transport scope');
END;
CREATE TABLE tool_runtime_resource_events (
    event_id TEXT PRIMARY KEY,
    resource_id TEXT,
    tool_invocation_id TEXT,
    action_id TEXT,
    event_type TEXT NOT NULL,
    message TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (resource_id)
        REFERENCES tool_runtime_resources(resource_id) ON DELETE SET NULL,
    FOREIGN KEY (tool_invocation_id)
        REFERENCES tool_invocations(invocation_id) ON DELETE SET NULL
);
CREATE INDEX idx_tool_runtime_resource_events_invocation_created ON tool_runtime_resource_events(tool_invocation_id, created_at ASC);
CREATE INDEX idx_tool_runtime_resource_events_resource_created ON tool_runtime_resource_events(resource_id, created_at ASC);
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
    status TEXT NOT NULL CHECK (status IN ('pending', 'approved_once', 'denied')),
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
CREATE INDEX idx_approval_sessions_action_status ON approval_sessions(action_id, status, requested_at DESC);
CREATE INDEX idx_approval_sessions_tool_invocation_status ON approval_sessions(tool_invocation_id, status, requested_at DESC);
CREATE INDEX idx_approval_sessions_user_tool_request_status ON approval_sessions(user_id, tool_request_id, status, requested_at DESC);
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
CREATE INDEX idx_file_references_action_created ON file_references(action_id, created_at ASC);
CREATE INDEX idx_file_references_manifest ON file_references(manifest_id);
CREATE INDEX idx_file_references_tool_invocation ON file_references(tool_invocation_id);
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
CREATE INDEX idx_command_invocation_audits_outcome_created ON command_invocation_audits(terminal_outcome, created_at DESC);
CREATE INDEX idx_command_invocation_audits_exec_kind_created ON command_invocation_audits(execution_kind, created_at DESC);
DROP TABLE command_invocation_audits_legacy_v37;
DROP TABLE approval_sessions_legacy_v37;
DROP TABLE file_references_legacy_v37;
DROP TABLE workspace_manifest_mounts_legacy_v37;
DROP TABLE workspace_manifests_legacy_v37;
DROP TABLE tool_runtime_resource_events_legacy_v37;
DROP TABLE tool_runtime_resources_legacy_v37;
DROP TABLE tool_outputs_legacy_v37;
DROP TABLE tool_invocations_legacy_v37;
DROP TABLE execution_sessions_legacy_v37;
DROP TABLE capability_grants_legacy_v37;
DROP TABLE approval_preferences_legacy_v37;
DROP TABLE IF EXISTS artifact_manifest;
DROP TABLE IF EXISTS workspaces;
DROP TABLE IF EXISTS allowed_roots;
