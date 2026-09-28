import { useSortable } from '@dnd-kit/sortable';
import { CSS } from '@dnd-kit/utilities';
import { ChevronDown, ChevronRight, GripVertical, Trash2 } from 'lucide-react';
import { useState } from 'react';

import type { Translate } from '../types';
import { WorkspaceFolderRow } from './WorkspaceFolderRow';
import { ProjectOrganizationEditor } from './ProjectOrganizationEditor';
import {
  displayNameFromPath,
  successorFocusKey,
  workspaceFocusId,
  type FocusRequest,
  type WorkspaceFolder,
  type WorkspaceFolderCreateInput,
  type WorkspaceOrganization,
  type WorkspaceProject,
} from './workspaceSettingsModel';

interface SortableProjectCardProps {
  disabled: boolean;
  folders: WorkspaceFolder[];
  organizations: WorkspaceOrganization[];
  project: WorkspaceProject;
  t: Translate;
  onCreateFolder: (input: WorkspaceFolderCreateInput) => Promise<boolean>;
  onCreateOrganization: (displayName: string) => Promise<string | null>;
  onDeleteFolder: (folderId: string, focus: FocusRequest) => Promise<void>;
  onDeleteProject: (projectId: string) => Promise<void>;
  onSelectFolder: () => Promise<string | null>;
  onUpdateOrganizations: (
    projectId: string,
    organizationIds: string[],
    focus: FocusRequest
  ) => Promise<boolean>;
  createFolderBusy: boolean;
  deleteProjectBusy: boolean;
  isDeleteFolderBusy: (folderId: string) => boolean;
  organizationCreateBusy: boolean;
  projectLinksBusy: boolean;
}

export function SortableProjectCard(props: SortableProjectCardProps) {
  const [isExpanded, setIsExpanded] = useState(props.folders.length === 0);
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
    id: props.project.project_id,
    disabled: props.disabled,
  });

  const chooseFolder = async () => {
    const selectedPath = await props.onSelectFolder();
    if (!selectedPath) return;
    await props.onCreateFolder({
      displayName: displayNameFromPath(selectedPath),
      realPath: selectedPath,
      organizationIds: [],
      projectIds: [props.project.project_id],
    });
  };

  return (
    <article
      ref={setNodeRef}
      className={`workspace-project-card${isDragging ? ' is-dragging' : ''}`}
      data-project-id={props.project.project_id}
      style={{ transform: CSS.Transform.toString(transform), transition }}
    >
      <div className="workspace-project-card-header">
        <button
          type="button"
          className="workspace-project-drag-handle"
          disabled={props.disabled}
          aria-label={props.t('settings.workspace.drag.handle', {
            name: props.project.display_name,
          })}
          {...attributes}
          {...listeners}
        >
          <GripVertical size={15} aria-hidden="true" />
        </button>
        <button
          type="button"
          className="workspace-project-disclosure"
          aria-expanded={isExpanded}
          onClick={() => setIsExpanded((current) => !current)}
        >
          {isExpanded ? (
            <ChevronDown size={15} aria-hidden="true" />
          ) : (
            <ChevronRight size={15} aria-hidden="true" />
          )}
          <span className="workspace-project-name">{props.project.display_name}</span>
        </button>

        <ProjectOrganizationEditor
          busy={props.projectLinksBusy}
          createBusy={props.organizationCreateBusy}
          organizations={props.organizations}
          project={props.project}
          t={props.t}
          onCreateOrganization={props.onCreateOrganization}
          onUpdate={props.onUpdateOrganizations}
        />

        <span
          className={`workspace-project-folder-count${props.folders.length === 0 ? ' is-empty' : ''}`}
        >
          {props.t('settings.workspace.folderCount', { count: props.folders.length })}
        </span>

        <button
          type="button"
          className="workspace-icon-button workspace-project-delete"
          id={workspaceFocusId.projectDelete(props.project.project_id)}
          aria-label={`${props.t('common.delete')} ${props.project.display_name}`}
          aria-busy={props.deleteProjectBusy}
          title={props.t('common.delete')}
          onClick={() => void props.onDeleteProject(props.project.project_id)}
        >
          <Trash2 size={14} aria-hidden="true" />
        </button>
      </div>

      {isExpanded ? (
        <div className="workspace-project-card-details">
          {props.folders.map((folder) => (
            <WorkspaceFolderRow
              key={folder.folder_id}
              folder={folder}
              busy={props.isDeleteFolderBusy(folder.folder_id)}
              deleteButtonId={workspaceFocusId.projectFolderDelete(
                props.project.project_id,
                folder.folder_id
              )}
              t={props.t}
              onDelete={(folderId) => {
                const folderIds = props.folders.map((candidate) => candidate.folder_id);
                return props.onDeleteFolder(folderId, {
                  onSuccess: successorFocusKey(
                    folderIds,
                    folderId,
                    (successorId) =>
                      workspaceFocusId.projectFolderDelete(props.project.project_id, successorId),
                    workspaceFocusId.projectFolderAdd(props.project.project_id)
                  ),
                  onFailure: workspaceFocusId.projectFolderDelete(
                    props.project.project_id,
                    folderId
                  ),
                });
              }}
            />
          ))}
          <button
            type="button"
            id={workspaceFocusId.projectFolderAdd(props.project.project_id)}
            aria-busy={props.createFolderBusy}
            onClick={() => void chooseFolder()}
            className="workspace-button workspace-button-primary workspace-project-add-folder"
          >
            {props.t('settings.workspace.selectFolder')}
          </button>
        </div>
      ) : null}
    </article>
  );
}
