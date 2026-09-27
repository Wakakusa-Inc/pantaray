ALTER TABLE activity_logs
ADD COLUMN thinking TEXT;

ALTER TABLE activity_summaries
ADD COLUMN thinking TEXT;

ALTER TABLE agent_insight_update_run_steps
ADD COLUMN thinking TEXT;

ALTER TABLE agent_fact_structuring_run_steps
ADD COLUMN thinking TEXT;
