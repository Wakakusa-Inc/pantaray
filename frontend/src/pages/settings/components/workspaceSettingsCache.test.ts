import { afterEach, describe, expect, it } from 'vitest';

import {
  clearWorkspaceSettingsCache,
  getCachedWorkspaceSettings,
  setCachedWorkspaceSettings,
} from './workspaceSettingsCache';

describe('workspaceSettingsCache', () => {
  afterEach(clearWorkspaceSettingsCache);

  it('preserves scalar sort_order while cloning project arrays', () => {
    const settings = {
      read_access_scope: 'workspace' as const,
      organizations: [],
      projects: [
        {
          project_id: 'project-a',
          display_name: 'Project A',
          sort_order: 7,
          organization_ids: ['org-a'],
        },
      ],
      folders: [],
    };

    setCachedWorkspaceSettings('user-1', settings);
    settings.projects[0].sort_order = 99;
    settings.projects[0].organization_ids.push('org-b');

    expect(getCachedWorkspaceSettings('user-1')?.projects).toEqual([
      {
        project_id: 'project-a',
        display_name: 'Project A',
        sort_order: 7,
        organization_ids: ['org-a'],
      },
    ]);
  });
});
