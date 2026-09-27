import { describe, expect, it } from 'vitest';

import { moveProject } from './useWorkspaceProjectDragController';
import type { WorkspaceProject } from './components/workspaceSettingsModel';

const projects: WorkspaceProject[] = [
  { project_id: 'project-a', display_name: 'A', sort_order: 0, organization_ids: ['org-a'] },
  { project_id: 'project-b', display_name: 'B', sort_order: 1, organization_ids: [] },
  { project_id: 'project-c', display_name: 'C', sort_order: 2, organization_ids: ['org-a'] },
];

describe('moveProject', () => {
  it('moves a project in the complete persisted order without mutating the input', () => {
    const moved = moveProject(projects, 'project-c', 'project-a');

    expect(moved.map((project) => project.project_id)).toEqual([
      'project-c',
      'project-a',
      'project-b',
    ]);
    expect(moved.map((project) => project.sort_order)).toEqual([0, 1, 2]);
    expect(projects.map((project) => project.project_id)).toEqual([
      'project-a',
      'project-b',
      'project-c',
    ]);
  });

  it('leaves the project array unchanged for a missing drop target', () => {
    expect(moveProject(projects, 'project-a', 'missing')).toBe(projects);
  });
});
