CREATE TABLE IF NOT EXISTS agent_suggestion_critics (
    critic_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    suggestion_id TEXT,
    model TEXT NOT NULL,
    decision TEXT NOT NULL CHECK (decision IN ('triggered', 'suppressed')),
    critic_score INTEGER CHECK (critic_score IS NULL OR (critic_score >= 0 AND critic_score <= 100)),
    status TEXT NOT NULL CHECK (status IN ('success', 'error')),
    critic_input TEXT NOT NULL CHECK (json_valid(critic_input)),
    prompt_text TEXT,
    response_text TEXT,
    thinking TEXT,
    embeddings_artifact_path TEXT,
    latency_ms INTEGER CHECK (latency_ms IS NULL OR latency_ms >= 0),
    error TEXT CHECK (error IS NULL OR json_valid(error)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
    FOREIGN KEY (suggestion_id) REFERENCES agent_suggestions(suggestion_id) ON DELETE SET NULL
);

CREATE INDEX idx_agent_suggestion_critics_user_created ON agent_suggestion_critics(user_id, created_at DESC);
CREATE INDEX idx_agent_suggestion_critics_suggestion ON agent_suggestion_critics(suggestion_id);

CREATE TABLE IF NOT EXISTS action_desires (
    desire_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    action_id TEXT NOT NULL,
    desire_type TEXT NOT NULL,
    content TEXT NOT NULL,
    position INTEGER NOT NULL CHECK (position >= 0),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
    FOREIGN KEY (action_id) REFERENCES agent_actions(action_id) ON DELETE CASCADE,
    UNIQUE (action_id, position)
);

CREATE TABLE IF NOT EXISTS action_check_items (
    check_item_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    action_id TEXT NOT NULL,
    title TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('open', 'done', 'dropped')),
    position INTEGER NOT NULL CHECK (position >= 0),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
    FOREIGN KEY (action_id) REFERENCES agent_actions(action_id) ON DELETE CASCADE,
    UNIQUE (action_id, position)
);

CREATE TABLE IF NOT EXISTS action_goals (
    goal_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    action_id TEXT NOT NULL,
    check_item_id TEXT,
    title TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('open', 'done', 'dropped')),
    is_active INTEGER NOT NULL CHECK (is_active IN (0, 1)),
    note TEXT,
    position INTEGER NOT NULL CHECK (position >= 0),
    dependencies_json TEXT NOT NULL CHECK (json_valid(dependencies_json)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
    FOREIGN KEY (action_id) REFERENCES agent_actions(action_id) ON DELETE CASCADE,
    FOREIGN KEY (check_item_id) REFERENCES action_check_items(check_item_id) ON DELETE SET NULL,
    UNIQUE (action_id, position)
);

CREATE INDEX idx_action_goals_action_status ON action_goals(action_id, status, position ASC);

CREATE TABLE IF NOT EXISTS action_requirements (
    requirement_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    action_id TEXT NOT NULL,
    goal_id TEXT NOT NULL,
    content TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('open', 'satisfied', 'assumed', 'dropped')),
    is_active INTEGER NOT NULL CHECK (is_active IN (0, 1)),
    data_json TEXT CHECK (data_json IS NULL OR json_valid(data_json)),
    note TEXT,
    importance TEXT,
    difficulty TEXT,
    position INTEGER NOT NULL CHECK (position >= 0),
    dependencies_json TEXT NOT NULL CHECK (json_valid(dependencies_json)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
    FOREIGN KEY (action_id) REFERENCES agent_actions(action_id) ON DELETE CASCADE,
    FOREIGN KEY (goal_id) REFERENCES action_goals(goal_id) ON DELETE CASCADE,
    UNIQUE (goal_id, position)
);

CREATE INDEX idx_action_requirements_goal_status ON action_requirements(goal_id, status, position ASC);

CREATE TABLE IF NOT EXISTS action_completed_goals (
    completed_goal_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    action_id TEXT NOT NULL,
    goal_id TEXT NOT NULL,
    goal_title TEXT NOT NULL,
    goal_output TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
    FOREIGN KEY (action_id) REFERENCES agent_actions(action_id) ON DELETE CASCADE,
    FOREIGN KEY (goal_id) REFERENCES action_goals(goal_id) ON DELETE CASCADE,
    UNIQUE (action_id, goal_id)
);

CREATE TABLE IF NOT EXISTS allowed_roots (
    root_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    bookmark_data BLOB NOT NULL,
    normalized_path TEXT NOT NULL,
    access_mode TEXT NOT NULL CHECK (access_mode IN ('read', 'read_write')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
    UNIQUE (user_id, normalized_path)
);

CREATE TABLE IF NOT EXISTS workspaces (
    workspace_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('user_repo', 'user_folder', 'app_project', 'scratch')),
    root_id TEXT,
    normalized_path TEXT NOT NULL,
    repo_root_path TEXT,
    vcs_kind TEXT NOT NULL CHECK (vcs_kind IN ('git', 'none')),
    toolchain_hint_json TEXT NOT NULL CHECK (json_valid(toolchain_hint_json)),
    trust_level TEXT NOT NULL CHECK (trust_level IN ('user_selected', 'app_managed', 'ephemeral')),
    default_exec_policy_json TEXT NOT NULL CHECK (json_valid(default_exec_policy_json)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
    FOREIGN KEY (root_id) REFERENCES allowed_roots(root_id) ON DELETE SET NULL
);

CREATE UNIQUE INDEX idx_workspaces_user_path ON workspaces(user_id, normalized_path);

CREATE TABLE IF NOT EXISTS execution_sessions (
    execution_session_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    action_id TEXT,
    parent_execution_session_id TEXT,
    workspace_id TEXT NOT NULL,
    exec_mode TEXT NOT NULL CHECK (exec_mode IN ('brokered_file_ops', 'workspace_command')),
    cwd_path TEXT NOT NULL,
    action_temp_dir TEXT,
    app_runtime_python TEXT,
    network_policy TEXT NOT NULL,
    capability_snapshot_json TEXT NOT NULL CHECK (json_valid(capability_snapshot_json)),
    tool_allowlist_json TEXT CHECK (tool_allowlist_json IS NULL OR json_valid(tool_allowlist_json)),
    status TEXT NOT NULL CHECK (status IN ('running', 'completed', 'failed', 'canceled', 'expired')),
    started_at TEXT NOT NULL,
    completed_at TEXT,
    expires_at TEXT,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
    FOREIGN KEY (action_id) REFERENCES agent_actions(action_id) ON DELETE CASCADE,
    FOREIGN KEY (parent_execution_session_id) REFERENCES execution_sessions(execution_session_id) ON DELETE SET NULL,
    FOREIGN KEY (workspace_id) REFERENCES workspaces(workspace_id) ON DELETE CASCADE
);

CREATE INDEX idx_execution_sessions_action_started ON execution_sessions(action_id, started_at ASC);

CREATE TABLE IF NOT EXISTS tool_definitions (
    tool_id TEXT PRIMARY KEY,
    tool_name TEXT NOT NULL,
    tool_description TEXT NOT NULL,
    category TEXT NOT NULL,
    risk_level TEXT NOT NULL,
    input_schema_json TEXT NOT NULL CHECK (json_valid(input_schema_json)),
    output_schema_json TEXT CHECK (output_schema_json IS NULL OR json_valid(output_schema_json)),
    rate_limit_json TEXT CHECK (rate_limit_json IS NULL OR json_valid(rate_limit_json)),
    is_enabled INTEGER NOT NULL CHECK (is_enabled IN (0, 1)),
    version TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tool_invocations (
    invocation_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    action_id TEXT NOT NULL,
    step_id TEXT,
    tool_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
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
            'automation_control'
        )
    ),
    network_policy TEXT,
    command_summary TEXT,
    capability_snapshot_json TEXT CHECK (capability_snapshot_json IS NULL OR json_valid(capability_snapshot_json)),
    started_at TEXT NOT NULL,
    completed_at TEXT,
    status TEXT NOT NULL CHECK (status IN ('queued', 'running', 'completed', 'failed', 'canceled', 'timed_out')),
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
    FOREIGN KEY (action_id) REFERENCES agent_actions(action_id) ON DELETE CASCADE,
    FOREIGN KEY (step_id) REFERENCES agent_action_steps(step_id) ON DELETE SET NULL,
    FOREIGN KEY (tool_id) REFERENCES tool_definitions(tool_id) ON DELETE RESTRICT,
    FOREIGN KEY (workspace_id) REFERENCES workspaces(workspace_id) ON DELETE CASCADE,
    FOREIGN KEY (execution_session_id) REFERENCES execution_sessions(execution_session_id) ON DELETE CASCADE
);

CREATE INDEX idx_tool_invocations_action_started ON tool_invocations(action_id, started_at ASC);
CREATE INDEX idx_tool_invocations_step ON tool_invocations(step_id);

CREATE TABLE IF NOT EXISTS tool_outputs (
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

CREATE TABLE IF NOT EXISTS tool_redactions (
    redaction_id TEXT PRIMARY KEY,
    output_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    reason TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (output_id) REFERENCES tool_outputs(output_id) ON DELETE CASCADE
);

CREATE INDEX idx_tool_redactions_output ON tool_redactions(output_id);
