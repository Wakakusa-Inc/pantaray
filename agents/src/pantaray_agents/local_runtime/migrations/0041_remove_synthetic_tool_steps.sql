PRAGMA foreign_keys = ON;

UPDATE tool_invocations
SET step_id = NULL
WHERE step_id IN (
    SELECT step_id
    FROM agent_action_steps
    WHERE short_step_id LIKE 'synthetic-%-TOOL'
);

DELETE FROM agent_action_steps
WHERE short_step_id LIKE 'synthetic-%-TOOL';
