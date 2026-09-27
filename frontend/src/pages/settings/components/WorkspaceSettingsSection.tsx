import { useLayoutEffect } from 'react';

import type { Translate } from '../types';
import {
  useWorkspaceSettingsController,
  workspacePendingKey,
  type WorkspacePendingKey,
} from '../useWorkspaceSettingsController';
import { WorkspaceListToolbar } from './WorkspaceListToolbar';
import { WorkspaceProjectList } from './WorkspaceProjectList';
import { WorkspaceUnassignedFolders } from './WorkspaceUnassignedFolders';
import './workspaceSettings.css';
import './workspaceProjectList.css';
import './workspaceOrganizations.css';
import './workspaceProjectDnd.css';

type WorkspaceSettingsSectionProps = {
  t: Translate;
};

export function WorkspaceSettingsSection({ t }: WorkspaceSettingsSectionProps) {
  const controller = useWorkspaceSettingsController(t);
  const { clearFocusRequest, focusRequest, settings } = controller;
  const isPending = (key: WorkspacePendingKey) => controller.pending.has(key);

  useLayoutEffect(() => {
    const request = focusRequest;
    if (!request) return;
    document.getElementById(request.key)?.focus();
    clearFocusRequest(request);
  }, [clearFocusRequest, focusRequest]);

  return (
    <div className="dashboard-section workspace-page">
      <div className="workspace-page-header">
        <h3 className="dashboard-section-title">{t('settings.workspace.title')}</h3>
        <p className="dashboard-section-description">{t('settings.workspace.description')}</p>
      </div>

      <div className="workspace-settings-grid">
        {settings === null ? (
          <div className="workspace-structure-scroll">
            <div className="workspace-project-list workspace-project-list-status">
              {controller.showLoading ? (
                <div className="history-loading">{t('common.loading')}</div>
              ) : (
                // Nothing was read, so there is no workspace to edit here: showing the
                // empty lists would offer defaults nobody confirmed as the current ones.
                <div className="history-error" role="alert">
                  {controller.errorMessage}
                </div>
              )}
            </div>
          </div>
        ) : (
          <>
            <WorkspaceListToolbar
              organizations={settings.organizations}
              projects={settings.projects}
              folders={settings.folders}
              organizationCreateBusy={isPending(workspacePendingKey.organizationCreate)}
              projectCreateBusy={isPending(workspacePendingKey.projectCreate)}
              t={t}
              onCreateOrganization={controller.addOrganization}
              onCreateProject={controller.createProject}
              onDeleteOrganization={controller.deleteOrganization}
              isOrganizationDeleteBusy={(organizationId) =>
                isPending(workspacePendingKey.organizationDelete(organizationId))
              }
            />
            <div className="workspace-structure-scroll">
              <WorkspaceProjectList
                organizations={settings.organizations}
                projects={settings.projects}
                folders={settings.folders}
                disabled={controller.isProjectStructurePending}
                dragController={controller.dragController}
                statusMessage={controller.errorMessage ?? undefined}
                t={t}
                onCreateFolder={controller.createFolder}
                onSelectFolder={controller.selectFolder}
                onDeleteProject={controller.deleteProject}
                onDeleteFolder={controller.deleteFolder}
                onUpdateProjectOrganizations={controller.updateProjectOrganizations}
                isCreateFolderBusy={(projectId) =>
                  isPending(workspacePendingKey.folderCreate(projectId))
                }
                isDeleteFolderBusy={(folderId) =>
                  isPending(workspacePendingKey.folderDelete(folderId))
                }
                isDeleteProjectBusy={(projectId) =>
                  isPending(workspacePendingKey.projectDelete(projectId))
                }
                isProjectLinksBusy={(projectId) =>
                  isPending(workspacePendingKey.projectLinks(projectId))
                }
              />
              <WorkspaceUnassignedFolders
                organizations={settings.organizations}
                projects={settings.projects}
                folders={settings.folders}
                t={t}
                onAssign={controller.assignFolderToProject}
                onDeleteFolder={controller.deleteFolder}
                isAssignBusy={(folderId) => isPending(workspacePendingKey.folderLinks(folderId))}
                isDeleteFolderBusy={(folderId) =>
                  isPending(workspacePendingKey.folderDelete(folderId))
                }
              />
            </div>
          </>
        )}
      </div>
    </div>
  );
}
