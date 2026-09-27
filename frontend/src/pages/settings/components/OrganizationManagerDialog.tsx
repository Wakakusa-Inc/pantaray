import { Trash2, X } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';

import type { Translate } from '../types';
import { InlineTextForm } from './WorkspaceSettingsFormControls';
import {
  compareOrganizations,
  countOrganizationUsage,
  successorFocusKey,
  workspaceFocusId,
  type FocusRequest,
  type WorkspaceFolder,
  type WorkspaceOrganization,
  type WorkspaceProject,
} from './workspaceSettingsModel';

interface OrganizationManagerDialogProps {
  createBusy: boolean;
  folders: WorkspaceFolder[];
  isOpen: boolean;
  organizations: WorkspaceOrganization[];
  projects: WorkspaceProject[];
  t: Translate;
  onClose: () => void;
  onCreate: (displayName: string) => Promise<boolean>;
  onDelete: (organizationId: string, focus: FocusRequest) => Promise<void>;
  isDeleteBusy: (organizationId: string) => boolean;
}

export function OrganizationManagerDialog(props: OrganizationManagerDialogProps) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const [organizationName, setOrganizationName] = useState('');
  const sortedOrganizations = [...props.organizations].sort(compareOrganizations);
  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    if (props.isOpen) {
      if (!dialog.open) {
        dialog.showModal();
        inputRef.current?.focus();
      }
    } else if (dialog.open) {
      dialog.close();
    }
  }, [props.isOpen]);

  const addOrganization = async () => {
    const displayName = organizationName.trim();
    if (!displayName) return;
    if (await props.onCreate(displayName)) setOrganizationName('');
  };

  const close = () => {
    setOrganizationName('');
    props.onClose();
  };

  return (
    <dialog
      ref={dialogRef}
      className="workspace-organization-dialog"
      aria-labelledby="workspace-organization-dialog-title"
      onCancel={(event) => {
        event.preventDefault();
        close();
      }}
    >
      <div className="workspace-dialog-header">
        <h4 id="workspace-organization-dialog-title">
          {props.t('settings.workspace.organizationManager.title')}
        </h4>
        <button
          type="button"
          className="workspace-icon-button"
          aria-label={props.t('common.close')}
          onClick={close}
        >
          <X size={15} aria-hidden="true" />
        </button>
      </div>
      <InlineTextForm
        buttonLabel={props.t('settings.workspace.addOrganization')}
        busy={props.createBusy}
        disabled={!organizationName.trim()}
        onSubmit={() => void addOrganization()}
        placeholder={props.t('settings.workspace.organizationPlaceholder')}
        value={organizationName}
        onChange={setOrganizationName}
        inputRef={inputRef}
        inputId={workspaceFocusId.organizationInput}
      />
      <div className="workspace-organization-list">
        {sortedOrganizations.map((organization) => (
          <div key={organization.organization_id} className="workspace-organization-list-row">
            <span>{organization.display_name}</span>
            <span className="workspace-organization-usage">
              {props.t('settings.workspace.organizationManager.usage', {
                count: countOrganizationUsage(
                  organization.organization_id,
                  props.projects,
                  props.folders
                ),
              })}
            </span>
            <button
              type="button"
              className="workspace-icon-button"
              id={workspaceFocusId.organizationDelete(organization.organization_id)}
              aria-label={`${props.t('common.delete')} ${organization.display_name}`}
              aria-busy={props.isDeleteBusy(organization.organization_id)}
              onClick={() => {
                const organizationIds = sortedOrganizations.map(
                  (candidate) => candidate.organization_id
                );
                void props.onDelete(organization.organization_id, {
                  onSuccess: successorFocusKey(
                    organizationIds,
                    organization.organization_id,
                    workspaceFocusId.organizationDelete,
                    workspaceFocusId.organizationInput
                  ),
                  onFailure: workspaceFocusId.organizationDelete(organization.organization_id),
                });
              }}
            >
              <Trash2 size={14} aria-hidden="true" />
            </button>
          </div>
        ))}
      </div>
    </dialog>
  );
}
