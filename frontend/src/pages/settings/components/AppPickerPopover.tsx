import { useState, type RefObject } from 'react';

import { filterInstalledApps } from '../model';
import type { CaptureAppEntry, InstalledApp, Translate } from '../types';
import { useDismissablePopover } from '../useDismissablePopover';

interface AppPickerPopoverProps {
  installedApps: InstalledApp[];
  isLoading: boolean;
  listed: CaptureAppEntry[];
  loadError: string | null;
  triggerRef: RefObject<HTMLButtonElement>;
  t: Translate;
  onDismiss: () => void;
  onSelect: (app: InstalledApp) => void;
}

/** Searchable list of installed applications, anchored above its trigger button. */
export function AppPickerPopover(props: AppPickerPopoverProps) {
  const { installedApps, isLoading, listed, loadError, onDismiss, onSelect, t, triggerRef } = props;
  const [query, setQuery] = useState('');
  const { dismiss, popoverRef } = useDismissablePopover({ isOpen: true, triggerRef, onDismiss });
  const matches = filterInstalledApps(installedApps, query, listed);

  return (
    <div
      ref={popoverRef}
      className="recording-filter-popover"
      role="dialog"
      aria-label={t('settings.recordingFilter.apps.pickerLabel')}
    >
      <input
        className="recording-filter-search"
        type="search"
        value={query}
        placeholder={t('settings.recordingFilter.apps.searchPlaceholder')}
        aria-label={t('settings.recordingFilter.apps.searchPlaceholder')}
        onChange={(event) => setQuery(event.target.value)}
      />
      {loadError ? <p className="recording-filter-empty">{loadError}</p> : null}
      {!loadError && isLoading ? (
        <p className="recording-filter-empty">{t('settings.recordingFilter.apps.loading')}</p>
      ) : null}
      {!loadError && !isLoading ? (
        <div className="recording-filter-picker-list">
          {matches.length === 0 ? (
            <p className="recording-filter-empty">{t('settings.recordingFilter.apps.noMatches')}</p>
          ) : (
            matches.map((app) => (
              <button
                key={app.bundleId ?? app.name}
                type="button"
                className="recording-filter-picker-option"
                onClick={() => {
                  onSelect(app);
                  dismiss();
                }}
              >
                {app.iconDataUrl ? (
                  <img className="recording-filter-row-icon" src={app.iconDataUrl} alt="" />
                ) : (
                  <span className="recording-filter-row-icon" aria-hidden="true" />
                )}
                <span className="recording-filter-row-name">{app.name}</span>
              </button>
            ))
          )}
        </div>
      ) : null}
    </div>
  );
}
