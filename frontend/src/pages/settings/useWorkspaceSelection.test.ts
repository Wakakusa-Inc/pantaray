import { describe, expect, it } from 'vitest';

import { followProjectChange, resolveSelection } from './useWorkspaceSelection';

const project = (projectId: string) => ({ kind: 'project' as const, projectId });

describe('workspace selection', () => {
  it('selects a project that just appeared', () => {
    expect(followProjectChange(['a', 'b'], ['a', 'b', 'c'], project('a'))).toEqual(project('c'));
  });

  it('hands a deleted selection to the next project, else the one before it', () => {
    expect(followProjectChange(['a', 'b', 'c'], ['a', 'c'], project('b'))).toEqual(project('c'));
    expect(followProjectChange(['a', 'b', 'c'], ['a', 'b'], project('c'))).toEqual(project('b'));
    expect(followProjectChange(['a'], [], project('a'))).toBeNull();
    // A reorder or another project's deletion keeps the selection.
    expect(followProjectChange(['a', 'b', 'c'], ['c', 'a'], project('a'))).toEqual(project('a'));
  });

  it('falls back to the first project, then the unassigned folders, then nothing', () => {
    expect(resolveSelection(['a', 'b'], true, project('gone'))).toEqual(project('a'));
    expect(resolveSelection(['a'], false, { kind: 'unassigned' })).toEqual(project('a'));
    expect(resolveSelection([], true, null)).toEqual({ kind: 'unassigned' });
    expect(resolveSelection([], false, null)).toBeNull();
  });
});
