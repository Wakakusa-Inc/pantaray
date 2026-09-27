CREATE TABLE IF NOT EXISTS agent_suggestions (
    suggestion_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    status TEXT NOT NULL CHECK (
        status IN ('processing', 'success', 'error', 'timeout', 'canceled')
    ),
    answer TEXT,
    thinking TEXT,
    error TEXT CHECK (error IS NULL OR json_valid(error)),
    prompt_text TEXT,
    response_text TEXT,
    prompt_name TEXT,
    prompt_version TEXT,
    has_suggestion INTEGER CHECK (
        has_suggestion IS NULL OR has_suggestion IN (0, 1)
    ),
    request_images_count INTEGER NOT NULL DEFAULT 0 CHECK (request_images_count >= 0),
    used_images_count INTEGER NOT NULL DEFAULT 0 CHECK (used_images_count >= 0),
    interaction_contract TEXT CHECK (
        interaction_contract IS NULL
        OR interaction_contract IN ('action_offer', 'message_only')
    ),
    intervention_mode TEXT CHECK (
        intervention_mode IS NULL
        OR intervention_mode IN ('Executor', 'Mirror', 'Challenger', 'Editor', 'Witness')
    ),
    user_reaction TEXT CHECK (
        user_reaction IS NULL OR user_reaction IN ('accepted', 'rejected')
    ),
    accepted_at TEXT,
    rejected_at TEXT,
    action_status TEXT CHECK (
        action_status IS NULL
        OR action_status IN (
            'idle',
            'processing',
            'success',
            'error',
            'timeout',
            'canceled',
            'abandoned',
            'superseded'
        )
    ),
    action_failure_code TEXT,
    action_failure_stage TEXT,
    action_failure_message_public TEXT,
    action_request_payload TEXT CHECK (
        action_request_payload IS NULL OR json_valid(action_request_payload)
    ),
    action_process_id TEXT,
    action_execution_id TEXT,
    action_command_id TEXT,
    action_started_at TEXT,
    process_event_sequence INTEGER NOT NULL DEFAULT 0 CHECK (
        process_event_sequence >= 0
    ),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (user_id, suggestion_id),
    CHECK (interaction_contract <> 'message_only' OR user_reaction IS NULL),
    CHECK (
        action_failure_code IS NULL
        OR (
            LENGTH(action_failure_code) <= 64
            AND (
                action_failure_code GLOB 'ACTION_[A-Z0-9_]*'
                OR action_failure_code GLOB 'WS_[A-Z0-9_]*'
            )
        )
    ),
    CHECK (
        status = 'processing'
        OR has_suggestion IS NOT NULL
    ),
    CHECK (
        status = 'processing'
        OR (
            answer IS NOT NULL
            AND prompt_name IS NOT NULL
            AND prompt_version IS NOT NULL
            AND has_suggestion IS NOT NULL
        )
    ),
    CHECK (
        status <> 'success'
        OR (prompt_text IS NOT NULL AND response_text IS NOT NULL)
    ),
    CHECK (
        status = 'processing'
        OR (
            has_suggestion = 1
            AND interaction_contract IS NOT NULL
            AND intervention_mode IS NOT NULL
        )
        OR (
            has_suggestion = 0
            AND interaction_contract IS NULL
            AND intervention_mode IS NULL
        )
    ),
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
);

CREATE INDEX idx_agent_suggestions_user_created
ON agent_suggestions(user_id, created_at DESC);

CREATE INDEX idx_agent_suggestions_status_updated
ON agent_suggestions(status, updated_at DESC);

CREATE TABLE IF NOT EXISTS agent_actions (
    action_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    suggestion_id TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL CHECK (
        status IN ('processing', 'success', 'error', 'timeout', 'canceled')
    ),
    final_output TEXT NOT NULL,
    error TEXT CHECK (error IS NULL OR json_valid(error)),
    final_prompt_text TEXT,
    generation INTEGER NOT NULL DEFAULT 1 CHECK (generation >= 1),
    steps_budget INTEGER,
    llm_steps_budget INTEGER,
    tool_steps_budget INTEGER,
    token_budget INTEGER,
    total_steps INTEGER NOT NULL DEFAULT 0 CHECK (total_steps >= 0),
    total_llm_steps INTEGER NOT NULL DEFAULT 0 CHECK (total_llm_steps >= 0),
    total_tool_steps INTEGER NOT NULL DEFAULT 0 CHECK (total_tool_steps >= 0),
    total_prompt_tokens INTEGER NOT NULL DEFAULT 0 CHECK (
        total_prompt_tokens >= 0
    ),
    total_completion_tokens INTEGER NOT NULL DEFAULT 0 CHECK (
        total_completion_tokens >= 0
    ),
    total_tokens INTEGER NOT NULL DEFAULT 0 CHECK (total_tokens >= 0),
    prompt_name TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (user_id, action_id),
    CHECK (token_budget IS NULL OR token_budget > 0),
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
    FOREIGN KEY (suggestion_id) REFERENCES agent_suggestions(suggestion_id) ON DELETE CASCADE,
    FOREIGN KEY (user_id, suggestion_id) REFERENCES agent_suggestions(user_id, suggestion_id)
);

CREATE INDEX idx_agent_actions_user_created
ON agent_actions(user_id, created_at DESC);

CREATE INDEX idx_agent_actions_suggestion
ON agent_actions(suggestion_id);

CREATE INDEX idx_agent_actions_status_updated
ON agent_actions(status, updated_at DESC);

CREATE TABLE IF NOT EXISTS agent_action_steps (
    step_id TEXT PRIMARY KEY,
    action_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    parent_step_id TEXT,
    step_number INTEGER NOT NULL CHECK (step_number >= 1),
    local_step_number INTEGER,
    short_step_id TEXT,
    step_type TEXT NOT NULL CHECK (step_type IN ('llm_output', 'tool_execution')),
    step_name TEXT NOT NULL,
    status TEXT NOT NULL CHECK (
        status IN ('queued', 'processing', 'success', 'error', 'timeout')
    ),
    goal_handle TEXT,
    requirement_handle TEXT,
    parallel_group_id TEXT,
    parallel_depth INTEGER CHECK (parallel_depth IS NULL OR parallel_depth >= 0),
    parallel_index INTEGER CHECK (parallel_index IS NULL OR parallel_index >= 0),
    retry_count INTEGER NOT NULL DEFAULT 0 CHECK (retry_count >= 0),
    started_at TEXT,
    completed_at TEXT,
    execution_time_ms INTEGER CHECK (
        execution_time_ms IS NULL OR execution_time_ms >= 0
    ),
    prompt_tokens INTEGER NOT NULL DEFAULT 0 CHECK (prompt_tokens >= 0),
    completion_tokens INTEGER NOT NULL DEFAULT 0 CHECK (completion_tokens >= 0),
    thinking TEXT,
    llm_prompt_text TEXT,
    llm_response_text TEXT,
    tool_args TEXT CHECK (tool_args IS NULL OR json_valid(tool_args)),
    tool_output TEXT CHECK (tool_output IS NULL OR json_valid(tool_output)),
    runtime_state_checkpoint TEXT CHECK (
        runtime_state_checkpoint IS NULL OR json_valid(runtime_state_checkpoint)
    ),
    runtime_state_checkpoint_version INTEGER CHECK (
        runtime_state_checkpoint_version IS NULL
        OR runtime_state_checkpoint_version >= 1
    ),
    error TEXT CHECK (error IS NULL OR json_valid(error)),
    created_at TEXT NOT NULL,
    FOREIGN KEY (action_id) REFERENCES agent_actions(action_id) ON DELETE CASCADE,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
    FOREIGN KEY (parent_step_id) REFERENCES agent_action_steps(step_id) ON DELETE SET NULL,
    UNIQUE (action_id, step_number),
    UNIQUE (action_id, short_step_id),
    CHECK (local_step_number IS NULL OR local_step_number > 0),
    CHECK (
        (short_step_id IS NULL AND local_step_number IS NULL)
        OR (short_step_id IS NOT NULL AND local_step_number IS NOT NULL)
    ),
    CHECK (short_step_id IS NULL OR LENGTH(short_step_id) <= 128),
    CHECK (
        (runtime_state_checkpoint IS NULL AND runtime_state_checkpoint_version IS NULL)
        OR (
            runtime_state_checkpoint IS NOT NULL
            AND runtime_state_checkpoint_version IS NOT NULL
        )
    )
);

CREATE INDEX idx_agent_action_steps_action_created
ON agent_action_steps(action_id, created_at ASC);

CREATE INDEX idx_agent_action_steps_short_step_id
ON agent_action_steps(short_step_id);

CREATE INDEX idx_agent_action_steps_goal_handle
ON agent_action_steps(goal_handle);

CREATE INDEX idx_agent_action_steps_requirement_handle
ON agent_action_steps(requirement_handle);

CREATE TABLE IF NOT EXISTS agent_process_events (
    event_id TEXT PRIMARY KEY,
    suggestion_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    action_id TEXT,
    sequence INTEGER NOT NULL CHECK (sequence > 0),
    event_name TEXT NOT NULL CHECK (
        event_name IN (
            'process_started',
            'suggestion_chunk',
            'suggestion_reaction_committed',
            'action_requested',
            'action_summary',
            'completion_chunk',
            'process_completed',
            'error'
        )
    ),
    payload TEXT NOT NULL CHECK (json_valid(payload)),
    created_at TEXT NOT NULL,
    FOREIGN KEY (suggestion_id) REFERENCES agent_suggestions(suggestion_id) ON DELETE CASCADE,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
    FOREIGN KEY (action_id) REFERENCES agent_actions(action_id) ON DELETE CASCADE,
    UNIQUE (suggestion_id, sequence)
);

CREATE INDEX idx_agent_process_events_suggestion_sequence
ON agent_process_events(suggestion_id, sequence ASC);

CREATE INDEX idx_agent_process_events_user_created
ON agent_process_events(user_id, created_at DESC);

CREATE TABLE IF NOT EXISTS agent_suggestion_history (
    suggestion_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    suggestion_created_at TEXT NOT NULL,
    suggestion_updated_at TEXT NOT NULL,
    suggestion_status TEXT NOT NULL CHECK (
        suggestion_status IN ('processing', 'success', 'error', 'timeout', 'canceled')
    ),
    has_suggestion INTEGER NOT NULL CHECK (has_suggestion IN (0, 1)),
    answer TEXT NOT NULL,
    interaction_contract TEXT CHECK (
        interaction_contract IS NULL
        OR interaction_contract IN ('action_offer', 'message_only')
    ),
    intervention_mode TEXT CHECK (
        intervention_mode IS NULL
        OR intervention_mode IN ('Executor', 'Mirror', 'Challenger', 'Editor', 'Witness')
    ),
    user_reaction TEXT CHECK (
        user_reaction IS NULL OR user_reaction IN ('accepted', 'rejected')
    ),
    accepted_at TEXT,
    rejected_at TEXT,
    action_status TEXT CHECK (
        action_status IS NULL
        OR action_status IN (
            'idle',
            'processing',
            'success',
            'error',
            'timeout',
            'canceled',
            'abandoned',
            'superseded'
        )
    ),
    action_failure_code TEXT,
    action_failure_stage TEXT,
    action_failure_message_public TEXT,
    action_request_payload_present INTEGER NOT NULL DEFAULT 0 CHECK (
        action_request_payload_present IN (0, 1)
    ),
    action_id TEXT,
    action_created_at TEXT,
    action_updated_at TEXT,
    final_output TEXT,
    last_sequence INTEGER NOT NULL DEFAULT 0 CHECK (last_sequence >= 0),
    CHECK (interaction_contract <> 'message_only' OR user_reaction IS NULL),
    CHECK (
        (has_suggestion = 1 AND interaction_contract IS NOT NULL AND intervention_mode IS NOT NULL)
        OR (has_suggestion = 0 AND interaction_contract IS NULL AND intervention_mode IS NULL)
    ),
    FOREIGN KEY (suggestion_id) REFERENCES agent_suggestions(suggestion_id) ON DELETE CASCADE,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
    FOREIGN KEY (action_id) REFERENCES agent_actions(action_id) ON DELETE SET NULL
);

CREATE INDEX idx_agent_suggestion_history_user_created
ON agent_suggestion_history(user_id, suggestion_created_at DESC);

CREATE INDEX idx_agent_suggestion_history_visible
ON agent_suggestion_history(user_id, has_suggestion, suggestion_created_at DESC);
