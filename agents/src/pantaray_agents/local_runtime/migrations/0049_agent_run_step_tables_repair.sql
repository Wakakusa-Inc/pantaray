CREATE TABLE IF NOT EXISTS agent_insight_update_run_steps (
    insight_update_id TEXT NOT NULL,
    step_number INTEGER NOT NULL CHECK (step_number > 0),
    step_kind TEXT NOT NULL CHECK (step_kind IN ('llm', 'tool')),
    status TEXT NOT NULL CHECK (status IN ('processing', 'success', 'error')),
    llm_prompt_text TEXT,
    llm_response_text TEXT,
    tool_name TEXT,
    tool_input_json TEXT CHECK (tool_input_json IS NULL OR json_valid(tool_input_json)),
    tool_output_json TEXT CHECK (tool_output_json IS NULL OR json_valid(tool_output_json)),
    error_code TEXT,
    error_message TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    PRIMARY KEY (insight_update_id, step_number),
    FOREIGN KEY (insight_update_id) REFERENCES agent_insight_update_runs(insight_update_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_agent_insight_update_run_steps_run
ON agent_insight_update_run_steps(insight_update_id, step_number);

CREATE TABLE IF NOT EXISTS agent_fact_structuring_run_steps (
    fact_run_id TEXT NOT NULL,
    step_number INTEGER NOT NULL CHECK (step_number > 0),
    step_kind TEXT NOT NULL CHECK (step_kind IN ('llm', 'tool')),
    status TEXT NOT NULL CHECK (status IN ('processing', 'success', 'error')),
    llm_prompt_text TEXT,
    llm_response_text TEXT,
    tool_name TEXT,
    tool_input_json TEXT CHECK (tool_input_json IS NULL OR json_valid(tool_input_json)),
    tool_output_json TEXT CHECK (tool_output_json IS NULL OR json_valid(tool_output_json)),
    error_code TEXT,
    error_message TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    PRIMARY KEY (fact_run_id, step_number),
    FOREIGN KEY (fact_run_id) REFERENCES agent_fact_structuring_runs(fact_run_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_agent_fact_structuring_run_steps_run
ON agent_fact_structuring_run_steps(fact_run_id, step_number);
