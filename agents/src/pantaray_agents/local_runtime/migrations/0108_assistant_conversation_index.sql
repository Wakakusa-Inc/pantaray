DROP INDEX idx_agent_action_steps_action_timeline;

CREATE INDEX idx_agent_action_steps_action_timeline
ON agent_action_steps(action_id, step_number DESC, step_id DESC)
WHERE step_number IS NOT NULL
  AND step_type IN ('user_request', 'assistant_message', 'tool_execution');
