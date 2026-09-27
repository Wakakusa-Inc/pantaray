CREATE INDEX idx_agent_action_steps_adopted_user_timeline
ON agent_action_steps(
    user_id,
    action_id,
    step_number DESC,
    step_id DESC,
    adopted_process_id
)
WHERE step_number IS NOT NULL
  AND step_type = 'user_request'
  AND status = 'success'
  AND adopted_process_id IS NOT NULL;

CREATE INDEX idx_agent_action_steps_unadopted_user_sequence
ON agent_action_steps(
    user_id,
    action_id,
    accepted_sequence DESC,
    step_id DESC
)
WHERE step_type = 'user_request'
  AND step_number IS NULL
  AND adopted_process_id IS NULL
  AND accepted_sequence IS NOT NULL;
