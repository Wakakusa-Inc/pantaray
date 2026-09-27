import { DndContext } from '@dnd-kit/core';
import { SortableContext, verticalListSortingStrategy } from '@dnd-kit/sortable';

import type { Translate } from '../types';
import type { WorkspaceProjectDragController } from '../useWorkspaceProjectDragController';
import { SortableProjectCard } from './SortableProjectCard';
import type {
  FocusRequest,
  WorkspaceFolder,
  WorkspaceFolderCreateInput,
  WorkspaceOrganization,
  WorkspaceProject,
} from './workspaceSettingsModel';
import { successorFocusKey, workspaceFocusId } from './workspaceSettingsModel';

interface WorkspaceProjectListProps {
  disabled: boolean;
  dragController: WorkspaceProjectDragController;
  folders: WorkspaceFolder[];
  organizationCreateBusy: boolean;
  organizations: WorkspaceOrganization[];
  projects: WorkspaceProject[];
  statusMessage?: string;
  t: Translate;
  onCreateFolder: (input: WorkspaceFolderCreateInput) => Promise<boolean>;
  onCreateOrganization: (displayName: string) => Promise<string | null>;
  onDeleteFolder: (folderId: string, focus: FocusRequest) => Promise<void>;
  onDeleteProject: (projectId: string, focus: FocusRequest) => Promise<void>;
  onSelectFolder: () => Promise<string | null>;
  onUpdateProjectOrganizations: (
    projectId: string,
    organizationIds: string[],
    focus: FocusRequest
  ) => Promise<boolean>;
  isCreateFolderBusy: (projectId: string) => boolean;
  isDeleteFolderBusy: (folderId: string) => boolean;
  isDeleteProjectBusy: (projectId: string) => boolean;
  isProjectLinksBusy: (projectId: string) => boolean;
}

export function WorkspaceProjectList(props: WorkspaceProjectListProps) {
  return (
    <DndContext
      sensors={props.dragController.sensors}
      accessibility={props.dragController.accessibility}
      onDragStart={props.dragController.onDragStart}
      onDragOver={props.dragController.onDragOver}
      onDragEnd={props.dragController.onDragEnd}
      onDragCancel={props.dragController.onDragCancel}
    >
      <SortableContext
        items={props.projects.map((project) => project.project_id)}
        strategy={verticalListSortingStrategy}
      >
        <div
          className="workspace-project-list"
          aria-label={props.t('settings.workspace.structureAriaLabel')}
        >
          {props.statusMessage ? (
            <div className="workspace-status-error" role="alert">
              {props.statusMessage}
            </div>
          ) : null}
          {props.projects.map((project) => (
            <SortableProjectCard
              key={project.project_id}
              project={project}
              organizations={props.organizations}
              folders={props.folders.filter((folder) =>
                folder.project_ids.includes(project.project_id)
              )}
              disabled={props.disabled}
              t={props.t}
              onCreateFolder={props.onCreateFolder}
              onCreateOrganization={props.onCreateOrganization}
              onDeleteFolder={props.onDeleteFolder}
              onDeleteProject={(projectId) => {
                const projectIds = props.projects.map((candidate) => candidate.project_id);
                return props.onDeleteProject(projectId, {
                  onSuccess: successorFocusKey(
                    projectIds,
                    projectId,
                    workspaceFocusId.projectDelete,
                    workspaceFocusId.projectAdd
                  ),
                  onFailure: workspaceFocusId.projectDelete(projectId),
                });
              }}
              onSelectFolder={props.onSelectFolder}
              onUpdateOrganizations={props.onUpdateProjectOrganizations}
              createFolderBusy={props.isCreateFolderBusy(project.project_id)}
              deleteProjectBusy={props.isDeleteProjectBusy(project.project_id)}
              isDeleteFolderBusy={props.isDeleteFolderBusy}
              organizationCreateBusy={props.organizationCreateBusy}
              projectLinksBusy={props.isProjectLinksBusy(project.project_id)}
            />
          ))}
        </div>
      </SortableContext>
    </DndContext>
  );
}
