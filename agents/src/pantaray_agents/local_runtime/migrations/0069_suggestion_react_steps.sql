CREATE TABLE IF NOT EXISTS agent_suggestion_run_steps (
    suggestion_id TEXT NOT NULL,
    step_number INTEGER NOT NULL CHECK (step_number > 0),
    step_kind TEXT NOT NULL CHECK (step_kind IN ('llm', 'tool')),
    status TEXT NOT NULL CHECK (status IN ('processing', 'success', 'error')),
    llm_prompt_text TEXT,
    llm_response_text TEXT,
    tool_name TEXT,
    tool_input_json TEXT CHECK (
        tool_input_json IS NULL OR json_valid(tool_input_json)
    ),
    tool_output_json TEXT CHECK (
        tool_output_json IS NULL OR json_valid(tool_output_json)
    ),
    error_code TEXT,
    error_message TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    PRIMARY KEY (suggestion_id, step_number),
    FOREIGN KEY (suggestion_id)
        REFERENCES agent_suggestions(suggestion_id) ON DELETE CASCADE
);
