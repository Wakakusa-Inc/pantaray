import { useEffect, useState } from 'react';

import type { MessageKey } from '@/i18n/types';

type Props = {
  t: (key: MessageKey, vars?: Record<string, string | number>) => string;
};

export function CommandNetworkSettingsSection({ t }: Props) {
  const [enabled, setEnabled] = useState<boolean | null>(null);
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState<MessageKey | null>(null);
  const [reloadVersion, setReloadVersion] = useState(0);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const api = window.electron?.workspaceSettings;
        if (!api) throw new Error('Workspace settings bridge is unavailable.');
        const response = await api.getCommandNetwork();
        if (!cancelled) setEnabled(response.command_network_enabled);
      } catch {
        if (!cancelled) setError('settings.commandNetwork.loadFailed');
      }
    };
    void load();
    return () => {
      cancelled = true;
    };
  }, [reloadVersion]);

  const update = async () => {
    if (enabled === null || isSaving) return;
    setIsSaving(true);
    setError(null);
    const api = window.electron?.workspaceSettings;
    try {
      if (!api) throw new Error('Workspace settings bridge is unavailable.');
      const response = await api.updateCommandNetwork(!enabled);
      setEnabled(response.command_network_enabled);
    } catch {
      // A failed response does not prove the write failed; read the stored value.
      setEnabled(null);
      setError('settings.commandNetwork.saveFailed');
      try {
        if (!api) throw new Error('Workspace settings bridge is unavailable.');
        const response = await api.getCommandNetwork();
        setEnabled(response.command_network_enabled);
      } catch {
        setError('settings.commandNetwork.verifyFailed');
      }
    } finally {
      setIsSaving(false);
    }
  };

  return (
    <>
      <div className="settings-control-row">
        <div className="settings-control-copy">
          <div className="settings-control-title">{t('settings.commandNetwork.title')}</div>
          <p
            id="command-network-description"
            className="dashboard-section-description settings-control-description"
          >
            {t('settings.commandNetwork.description')}
          </p>
        </div>
        {enabled === null ? (
          <span className="dashboard-section-description" role="status">
            {t(error ? 'settings.commandNetwork.unavailable' : 'common.loading')}
          </span>
        ) : (
          <button
            type="button"
            role="switch"
            aria-checked={enabled}
            aria-label={t('settings.commandNetwork.title')}
            aria-describedby="command-network-description"
            className={`settings-toggle settings-toggle--fixed command-network-toggle${enabled ? ' settings-toggle--on' : ''}`}
            disabled={isSaving}
            onClick={() => void update()}
          >
            <span className="settings-toggle-thumb" />
            <span className="settings-toggle-label">{t(enabled ? 'common.on' : 'common.off')}</span>
          </button>
        )}
      </div>
      {error ? (
        <div>
          <p role="alert" className="dashboard-section-description settings-section-error">
            {t(error)}
          </p>
          <button
            type="button"
            className="settings-inline-link"
            disabled={isSaving}
            onClick={() => {
              setEnabled(null);
              setError(null);
              setReloadVersion((version) => version + 1);
            }}
          >
            {t('settings.commandNetwork.reload')}
          </button>
        </div>
      ) : null}
    </>
  );
}
