CREATE TABLE IF NOT EXISTS agent_long_term_insight_state (
    user_id TEXT PRIMARY KEY,
    source_insight_id TEXT NOT NULL,
    source_run_id TEXT NOT NULL,
    storage_path TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    insight_profile_brief TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS agent_insight_update_runs (
    insight_update_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    insight_id TEXT,
    status TEXT NOT NULL CHECK (status IN ('processing', 'success', 'error')),
    base_storage_path TEXT,
    base_sha256 TEXT,
    final_storage_path TEXT,
    final_sha256 TEXT,
    insight_profile_brief TEXT,
    error TEXT CHECK (error IS NULL OR json_valid(error)),
    prompt_name TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
);

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

CREATE INDEX IF NOT EXISTS idx_agent_insight_update_runs_user_updated
ON agent_insight_update_runs(user_id, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_agent_insight_update_runs_insight_updated
ON agent_insight_update_runs(insight_id, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_agent_insight_update_run_steps_run
ON agent_insight_update_run_steps(insight_update_id, step_number);

CREATE TABLE IF NOT EXISTS agent_fact_structuring_runs (
    fact_run_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    fact_id TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('processing', 'success', 'error')),
    base_storage_path TEXT,
    base_sha256 TEXT,
    final_storage_path TEXT,
    final_sha256 TEXT,
    facts_profile_brief TEXT,
    error TEXT CHECK (error IS NULL OR json_valid(error)),
    prompt_name TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    source_insight_ids TEXT CHECK (source_insight_ids IS NULL OR json_valid(source_insight_ids)),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
);

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

CREATE INDEX IF NOT EXISTS idx_agent_fact_structuring_runs_user_updated
ON agent_fact_structuring_runs(user_id, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_agent_fact_structuring_runs_fact_updated
ON agent_fact_structuring_runs(fact_id, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_agent_fact_structuring_run_steps_run
ON agent_fact_structuring_run_steps(fact_run_id, step_number);

INSERT OR IGNORE INTO agent_insight_update_runs (
    insight_update_id,
    user_id,
    insight_id,
    status,
    base_storage_path,
    base_sha256,
    final_storage_path,
    final_sha256,
    insight_profile_brief,
    error,
    prompt_name,
    prompt_version,
    created_at,
    updated_at
)
SELECT
    COALESCE(insight_update_id, 'legacy-' || insight_id),
    user_id,
    insight_id,
    'success',
    long_term_insight_storage_path,
    long_term_insight_sha256,
    long_term_insight_storage_path,
    long_term_insight_sha256,
    insight_profile_brief,
    NULL,
    prompt_name,
    prompt_version,
    created_at,
    updated_at
FROM agent_insights
WHERE long_term_insight_storage_path IS NOT NULL
  AND TRIM(long_term_insight_storage_path) != '';

INSERT OR IGNORE INTO agent_insight_update_run_steps (
    insight_update_id,
    step_number,
    step_kind,
    status,
    llm_prompt_text,
    llm_response_text,
    tool_name,
    tool_input_json,
    tool_output_json,
    error_code,
    error_message,
    created_at
)
SELECT
    COALESCE(insight_update_id, 'legacy-' || insight_id),
    1,
    'llm',
    'success',
    COALESCE(prompt_text, ''),
    response_text,
    NULL,
    NULL,
    NULL,
    NULL,
    NULL,
    updated_at
FROM agent_insights
WHERE long_term_insight_storage_path IS NOT NULL
  AND TRIM(long_term_insight_storage_path) != ''
  AND (
      prompt_text IS NOT NULL
      OR response_text IS NOT NULL
  );

INSERT OR IGNORE INTO agent_long_term_insight_state (
    user_id,
    source_insight_id,
    source_run_id,
    storage_path,
    sha256,
    insight_profile_brief,
    created_at,
    updated_at
)
SELECT
    user_id,
    insight_id,
    COALESCE(insight_update_id, 'legacy-' || insight_id),
    long_term_insight_storage_path,
    long_term_insight_sha256,
    insight_profile_brief,
    created_at,
    updated_at
FROM (
    SELECT
        *,
        ROW_NUMBER() OVER (
            PARTITION BY user_id
            ORDER BY updated_at DESC, created_at DESC, insight_id DESC
        ) AS row_number
    FROM agent_insights
    WHERE long_term_insight_storage_path IS NOT NULL
      AND TRIM(long_term_insight_storage_path) != ''
      AND long_term_insight_sha256 IS NOT NULL
      AND TRIM(long_term_insight_sha256) != ''
)
WHERE row_number = 1;
