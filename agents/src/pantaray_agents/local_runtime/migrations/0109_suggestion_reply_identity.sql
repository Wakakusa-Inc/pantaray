-- The snapshot owns the reply association independently of suggestion approval.
CREATE UNIQUE INDEX uq_agent_action_steps_reply_source
ON agent_action_steps(user_id, source_suggestion_id)
WHERE source_suggestion_id IS NOT NULL;
