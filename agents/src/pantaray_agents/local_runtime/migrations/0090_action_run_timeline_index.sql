DROP INDEX idx_agent_action_steps_adopted_process;

CREATE INDEX idx_agent_action_steps_adopted_process
ON agent_action_steps(
    user_id,
    action_id,
    adopted_process_id,
    step_number ASC,
    step_id ASC
)
WHERE adopted_process_id IS NOT NULL;
