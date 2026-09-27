import React from 'react';

import type { IdeFileRules, IdeSensitivePresets, Translate } from '../types';

interface IdeFileRulesSectionProps {
  ideFileRules: IdeFileRules | null;
  ideFileRulesError: string | null;
  ideSensitivePresets: IdeSensitivePresets;
  isLoadingIdeFileRules: boolean;
  setIdeSensitivePresetEnv: (value: boolean) => void | Promise<void>;
  t: Translate;
}

export function IdeFileRulesSection({
  ideFileRules,
  ideFileRulesError,
  ideSensitivePresets,
  isLoadingIdeFileRules,
  setIdeSensitivePresetEnv,
  t,
}: IdeFileRulesSectionProps): React.JSX.Element {
  return (
    <div className="dashboard-subsection">
      <h4 className="dashboard-subsection-title" style={{ margin: 0 }}>
        {t('settings.ideFileRules.title')}
        <span
          style={{
            fontSize: '12px',
            fontWeight: 400,
            color: 'var(--text-muted)',
            marginLeft: '8px',
          }}
        >
          {t('settings.ideFileRules.forVscodeCursor')}
        </span>
      </h4>

      <div style={{ fontSize: '12px', color: 'var(--text-muted)', marginTop: '8px' }}>
        {t('settings.ideFileRules.noIdeHint')}
      </div>

      {ideFileRulesError && (
        <div className="history-error" style={{ marginTop: '8px' }}>
          {ideFileRulesError}
        </div>
      )}

      {isLoadingIdeFileRules ? (
        <div className="history-loading" style={{ marginTop: '12px' }}>
          {t('settings.ideFileRules.loadingRules')}
        </div>
      ) : !ideFileRules ? null : (
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            gap: '12px',
            flexWrap: 'wrap',
            marginTop: '12px',
          }}
        >
          <div style={{ minWidth: 0, flex: '1 1 240px' }}>
            <div
              style={{
                fontSize: '12px',
                fontWeight: 600,
                color: 'var(--text-primary)',
              }}
            >
              {t('settings.ideFileRules.sensitivePresets.env.title')}
            </div>
            <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>
              {t('settings.ideFileRules.sensitivePresets.env.description')}
            </div>
          </div>
          <button
            type="button"
            role="switch"
            aria-checked={ideSensitivePresets.blockEnvFiles}
            aria-label={t('settings.ideFileRules.sensitivePresets.env.title')}
            className={[
              'settings-toggle',
              'settings-toggle--compact',
              ideSensitivePresets.blockEnvFiles ? 'settings-toggle--on' : null,
            ]
              .filter(Boolean)
              .join(' ')}
            onClick={() => void setIdeSensitivePresetEnv(!ideSensitivePresets.blockEnvFiles)}
          >
            <span className="settings-toggle-thumb" />
            <span className="settings-toggle-label">
              {ideSensitivePresets.blockEnvFiles
                ? t('settings.ideFileRules.state.block')
                : t('settings.ideFileRules.state.allow')}
            </span>
          </button>
        </div>
      )}
    </div>
  );
}
