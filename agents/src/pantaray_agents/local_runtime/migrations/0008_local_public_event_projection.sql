ALTER TABLE agent_process_events ADD COLUMN suggestion_id TEXT;
ALTER TABLE agent_process_events ADD COLUMN user_id TEXT;
ALTER TABLE agent_process_events ADD COLUMN action_id TEXT;
ALTER TABLE agent_process_events ADD COLUMN sequence INTEGER;

CREATE UNIQUE INDEX IF NOT EXISTS idx_agent_process_events_user_suggestion_sequence
ON agent_process_events(user_id, suggestion_id, sequence);

CREATE INDEX IF NOT EXISTS idx_agent_process_events_process_id
ON agent_process_events(process_id);

ALTER TABLE agent_suggestion_history ADD COLUMN answer TEXT;
ALTER TABLE agent_suggestion_history ADD COLUMN interaction_contract TEXT;
ALTER TABLE agent_suggestion_history ADD COLUMN intervention_mode TEXT;
ALTER TABLE agent_suggestion_history ADD COLUMN user_reaction TEXT;
ALTER TABLE agent_suggestion_history ADD COLUMN accepted_at TEXT;
ALTER TABLE agent_suggestion_history ADD COLUMN rejected_at TEXT;
ALTER TABLE agent_suggestion_history ADD COLUMN action_status TEXT;
ALTER TABLE agent_suggestion_history ADD COLUMN action_failure_code TEXT;
ALTER TABLE agent_suggestion_history ADD COLUMN action_failure_stage TEXT;
ALTER TABLE agent_suggestion_history ADD COLUMN action_failure_message_public TEXT;
ALTER TABLE agent_suggestion_history ADD COLUMN final_output TEXT;
ALTER TABLE agent_suggestion_history ADD COLUMN action_updated_at TEXT;
ALTER TABLE agent_suggestion_history ADD COLUMN suggestion_updated_at TEXT;
ALTER TABLE agent_suggestion_history ADD COLUMN last_sequence INTEGER NOT NULL DEFAULT 0;
ALTER TABLE agent_suggestion_history ADD COLUMN updated_at TEXT;
