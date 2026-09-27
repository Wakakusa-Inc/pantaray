import React from 'react';

import { useI18n } from '@/context/useI18n';
import { WorkspaceSettingsSection } from './settings/components/WorkspaceSettingsSection';

const WorkspacePage: React.FC = () => {
  const { t } = useI18n();
  return (
    <div className="dashboard-container workspace-dashboard-container">
      <WorkspaceSettingsSection t={t} />
    </div>
  );
};

export default WorkspacePage;
