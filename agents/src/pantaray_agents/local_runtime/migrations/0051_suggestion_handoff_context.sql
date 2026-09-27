ALTER TABLE agent_suggestions
ADD COLUMN suggestion_summary TEXT;

ALTER TABLE agent_suggestions
ADD COLUMN target_context_json TEXT CHECK (
    target_context_json IS NULL OR json_valid(target_context_json)
);
