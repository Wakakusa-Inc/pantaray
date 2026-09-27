PRAGMA foreign_keys = OFF;

CREATE TABLE agent_action_steps_v27 (
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

INSERT INTO agent_action_steps_v27(
    step_id,
    action_id,
    user_id,
    parent_step_id,
    step_number,
    local_step_number,
    short_step_id,
    step_type,
    step_name,
    status,
    goal_handle,
    requirement_handle,
    parallel_group_id,
    parallel_depth,
    parallel_index,
    retry_count,
    started_at,
    completed_at,
    execution_time_ms,
    prompt_tokens,
    completion_tokens,
    thinking,
    llm_prompt_text,
    llm_response_text,
    tool_args,
    tool_output,
    runtime_state_checkpoint,
    runtime_state_checkpoint_version,
    error,
    created_at
)
SELECT
    step_id,
    action_id,
    user_id,
    parent_step_id,
    step_number,
    local_step_number,
    short_step_id,
    step_type,
    step_name,
    status,
    goal_handle,
    requirement_handle,
    parallel_group_id,
    parallel_depth,
    parallel_index,
    retry_count,
    started_at,
    completed_at,
    execution_time_ms,
    prompt_tokens,
    completion_tokens,
    thinking,
    llm_prompt_text,
    llm_response_text,
    tool_args,
    tool_output,
    runtime_state_checkpoint,
    runtime_state_checkpoint_version,
    error,
    created_at
FROM agent_action_steps;

DROP TABLE agent_action_steps;

ALTER TABLE agent_action_steps_v27 RENAME TO agent_action_steps;

CREATE INDEX IF NOT EXISTS idx_agent_action_steps_action_created
ON agent_action_steps(action_id, created_at ASC);

CREATE INDEX IF NOT EXISTS idx_agent_action_steps_short_step_id_resolution
ON agent_action_steps(
    action_id,
    short_step_id,
    completed_at DESC,
    created_at DESC,
    step_id DESC
);

CREATE INDEX IF NOT EXISTS idx_agent_action_steps_goal_handle
ON agent_action_steps(goal_handle);

CREATE INDEX IF NOT EXISTS idx_agent_action_steps_requirement_handle
ON agent_action_steps(requirement_handle);

PRAGMA foreign_keys = ON;
