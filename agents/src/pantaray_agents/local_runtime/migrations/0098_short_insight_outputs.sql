ALTER TABLE agent_insights ADD COLUMN reconsideration_reason TEXT;

DELETE FROM memory_agent_triggers WHERE trigger_kind = 'insight_from_1h_summary';
