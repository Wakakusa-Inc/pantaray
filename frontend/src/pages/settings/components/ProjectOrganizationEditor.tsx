import { Plus, X } from 'lucide-react';
import { useCallback, useRef, useState } from 'react';

import type { Translate } from '../types';
import { useDismissablePopover } from '../useDismissablePopover';
import { OrganizationSelect } from './OrganizationSelect';
import {
  resolveProjectOrganizations,
  successorFocusKey,
  workspaceFocusId,
  type FocusRequest,
  type WorkspaceOrganization,
  type WorkspaceProject,
} from './workspaceSettingsModel';

interface ProjectOrganizationEditorProps {
  busy: boolean;
  organizations: WorkspaceOrganization[];
  project: WorkspaceProject;
  t: Translate;
  onUpdate: (projectId: string, organizationIds: string[], focus: FocusRequest) => Promise<boolean>;
}

export function ProjectOrganizationEditor(props: ProjectOrganizationEditorProps) {
  const addTriggerRef = useRef<HTMLButtonElement>(null);
  const [isOpen, setIsOpen] = useState(false);
  const organizations = resolveProjectOrganizations(props.project, props.organizations);
  const pickerLabel = props.t('settings.workspace.projectOrganization.select', {
    name: props.project.display_name,
  });

  const closePicker = useCallback(() => setIsOpen(false), []);
  const { dismiss, popoverRef } = useDismissablePopover({
    isOpen,
    triggerRef: addTriggerRef,
    onDismiss: closePicker,
  });

  const togglePicker = () => {
    if (isOpen) dismiss();
    else setIsOpen(true);
  };

  const selectOrganization = async (organizationId: string) => {
    dismiss();
    await props.onUpdate(props.project.project_id, [organizationId], {
      onSuccess: workspaceFocusId.projectOrganizationRemove(
        props.project.project_id,
        organizationId
      ),
      onFailure: workspaceFocusId.projectOrganizationAdd(props.project.project_id),
    });
  };

  const removeOrganization = async (organizationId: string) => {
    await props.onUpdate(
      props.project.project_id,
      props.project.organization_ids.filter((currentId) => currentId !== organizationId),
      {
        onSuccess: successorFocusKey(
          organizations.map((organization) => organization.organization_id),
          organizationId,
          (successorId) =>
            workspaceFocusId.projectOrganizationRemove(props.project.project_id, successorId),
          workspaceFocusId.projectOrganizationAdd(props.project.project_id)
        ),
        onFailure: workspaceFocusId.projectOrganizationRemove(
          props.project.project_id,
          organizationId
        ),
      }
    );
  };

  return (
    <div className="workspace-project-organization-editor">
      <div
        className="workspace-project-badges"
        aria-label={props.t('settings.workspace.organizations')}
      >
        {organizations.map((organization) => (
          <span key={organization.organization_id} className="workspace-organization-badge">
            <span className="workspace-organization-badge-label">{organization.display_name}</span>
            <button
              type="button"
              id={workspaceFocusId.projectOrganizationRemove(
                props.project.project_id,
                organization.organization_id
              )}
              className="workspace-organization-remove"
              aria-busy={props.busy}
              aria-label={props.t('settings.workspace.projectOrganization.remove', {
                name: organization.display_name,
              })}
              onClick={() => void removeOrganization(organization.organization_id)}
            >
              <X size={9} strokeWidth={3} aria-hidden="true" />
            </button>
          </span>
        ))}
        {organizations.length === 0 ? (
          <button
            ref={addTriggerRef}
            type="button"
            id={workspaceFocusId.projectOrganizationAdd(props.project.project_id)}
            className="workspace-organization-badge workspace-organization-add-trigger"
            aria-busy={props.busy}
            aria-label={pickerLabel}
            aria-haspopup="dialog"
            aria-expanded={isOpen}
            onClick={togglePicker}
          >
            <Plus size={11} strokeWidth={2.5} aria-hidden="true" />
          </button>
        ) : null}
      </div>

      {isOpen ? (
        <div
          ref={popoverRef}
          className="workspace-project-organization-popover"
          role="dialog"
          aria-label={pickerLabel}
          tabIndex={-1}
        >
          {props.organizations.length > 0 ? (
            <OrganizationSelect
              organizations={props.organizations}
              selectedOrganizationId={null}
              t={props.t}
              onSelect={(organizationId) => void selectOrganization(organizationId)}
            />
          ) : (
            <p className="workspace-organization-picker-empty">
              {props.t('settings.workspace.projectOrganization.empty')}
            </p>
          )}
        </div>
      ) : null}
    </div>
  );
}
