import { Check } from 'lucide-react';

import type { Translate } from '../types';
import { compareOrganizations, type WorkspaceOrganization } from './workspaceSettingsModel';

interface OrganizationSelectProps {
  organizations: WorkspaceOrganization[];
  selectedOrganizationId: string | null;
  t: Translate;
  onSelect: (organizationId: string) => void;
}

export function OrganizationSelect(props: OrganizationSelectProps) {
  const sortedOrganizations = [...props.organizations].sort(compareOrganizations);

  if (sortedOrganizations.length === 0) return null;

  return (
    <fieldset className="workspace-organization-select">
      <legend>{props.t('settings.workspace.organizations')}</legend>
      {sortedOrganizations.map((organization) => {
        const isSelected = props.selectedOrganizationId === organization.organization_id;
        return (
          <button
            key={organization.organization_id}
            type="button"
            aria-pressed={isSelected}
            onClick={() => props.onSelect(organization.organization_id)}
          >
            <span>{organization.display_name}</span>
            {isSelected ? <Check size={13} strokeWidth={2.5} aria-hidden="true" /> : null}
          </button>
        );
      })}
    </fieldset>
  );
}
