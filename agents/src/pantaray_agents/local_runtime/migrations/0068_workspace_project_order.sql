ALTER TABLE workspace_projects
ADD COLUMN sort_order INTEGER NOT NULL DEFAULT 0
CHECK (sort_order >= 0);

WITH ranked_projects AS (
    SELECT
        user_id,
        project_id,
        ROW_NUMBER() OVER (
            PARTITION BY user_id
            ORDER BY display_name ASC, project_id ASC
        ) - 1 AS next_sort_order
    FROM workspace_projects
)
UPDATE workspace_projects
SET sort_order = (
    SELECT ranked_projects.next_sort_order
    FROM ranked_projects
    WHERE ranked_projects.user_id = workspace_projects.user_id
      AND ranked_projects.project_id = workspace_projects.project_id
);

CREATE INDEX idx_workspace_projects_user_status_order
ON workspace_projects(
    user_id,
    status,
    sort_order ASC,
    display_name ASC,
    project_id ASC
);
