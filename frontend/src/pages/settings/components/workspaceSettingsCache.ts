type WorkspaceSettings = Awaited<
  ReturnType<NonNullable<NonNullable<Window['electron']>['workspaceSettings']>['get']>
>;

const workspaceSettingsCache = new Map<string, WorkspaceSettings>();

function cloneWorkspaceSettings(settings: WorkspaceSettings): WorkspaceSettings {
  return {
    read_access_scope: settings.read_access_scope,
    organizations: settings.organizations.map((organization) => ({ ...organization })),
    projects: settings.projects.map((project) => ({
      ...project,
      organization_ids: [...project.organization_ids],
    })),
    folders: settings.folders.map((folder) => ({
      ...folder,
      organization_ids: [...folder.organization_ids],
      project_ids: [...folder.project_ids],
    })),
  };
}

export function getCachedWorkspaceSettings(userId: string): WorkspaceSettings | null {
  const cached = workspaceSettingsCache.get(userId);
  return cached ? cloneWorkspaceSettings(cached) : null;
}

export function setCachedWorkspaceSettings(userId: string, settings: WorkspaceSettings): void {
  workspaceSettingsCache.set(userId, cloneWorkspaceSettings(settings));
}

export function clearWorkspaceSettingsCache(): void {
  workspaceSettingsCache.clear();
}
