import { Globe } from 'lucide-react';

import { captureAppKey, findInstalledApp } from '../model';
import type { CaptureFilter, InstalledApp, Translate } from '../types';
import './recordingFilter.css';

/**
 * Entries shown as their own chip before the rest collapse into a count.
 *
 * The summary is a glance, not the editor: past a handful of chips the row wraps to
 * several lines and stops reading as one answer, and the exact remainder is one click
 * away in the dialog.
 */
const SUMMARY_CHIP_LIMIT = 8;

interface RecordingFilterSectionProps {
  hasCaptureSettings: boolean;
  captureFilter: CaptureFilter;
  captureFilterError: string | null;
  installedApps: InstalledApp[];
  isLoadingCaptureFilter: boolean;
  openFilterDialog: () => void | Promise<void>;
  t: Translate;
}

/** Read-only summary of the recording filter, with the button that opens the editor. */
export function RecordingFilterSection(props: RecordingFilterSectionProps) {
  const { captureFilter, installedApps, t } = props;
  const appsMode = t(
    captureFilter.apps.mode === 'exclude'
      ? 'settings.recordingFilter.apps.mode.exclude'
      : 'settings.recordingFilter.apps.mode.includeOnly'
  );
  const websitesMode = t(
    captureFilter.websites.mode === 'exclude'
      ? 'settings.recordingFilter.websites.mode.exclude'
      : 'settings.recordingFilter.websites.mode.includeOnly'
  );
  const shownApps = captureFilter.apps.entries.slice(0, SUMMARY_CHIP_LIMIT);
  const hiddenAppCount = captureFilter.apps.entries.length - shownApps.length;
  const shownHosts = captureFilter.websites.hosts.slice(0, SUMMARY_CHIP_LIMIT);
  const hiddenHostCount = captureFilter.websites.hosts.length - shownHosts.length;
  const moreChip = (count: number) =>
    count > 0 ? (
      <li className="recording-filter-chip recording-filter-chip-more">
        {t('settings.recordingFilter.summary.more', { count })}
      </li>
    ) : null;

  return (
    <div className="dashboard-subsection">
      <div className="settings-section-header">
        <div className="settings-section-heading">
          <h4 className="dashboard-subsection-title">{t('settings.recordingFilter.title')}</h4>
        </div>
        <button
          type="button"
          className="settings-action-button"
          disabled={!props.hasCaptureSettings || props.isLoadingCaptureFilter}
          onClick={() => void props.openFilterDialog()}
        >
          {t('settings.recordingFilter.edit')}
        </button>
      </div>

      {props.captureFilterError ? (
        <p className="dashboard-section-description settings-section-error" role="alert">
          {props.captureFilterError}
        </p>
      ) : null}

      {props.isLoadingCaptureFilter ? (
        <p className="dashboard-section-description">{t('settings.loadingStatus')}</p>
      ) : null}
      {props.hasCaptureSettings ? (
        <dl className="recording-filter-summary">
          <div className="recording-filter-summary-row">
            <dt>{appsMode}</dt>
            <dd>
              {captureFilter.apps.entries.length === 0 ? (
                t('settings.recordingFilter.summary.none')
              ) : (
                <ul
                  className="recording-filter-chips"
                  aria-label={t('settings.recordingFilter.apps.listLabel')}
                >
                  {shownApps.map((entry) => {
                    const iconDataUrl = findInstalledApp(installedApps, entry)?.iconDataUrl;
                    return (
                      <li key={captureAppKey(entry)} className="recording-filter-chip">
                        {iconDataUrl ? (
                          <img className="recording-filter-chip-icon" src={iconDataUrl} alt="" />
                        ) : (
                          <span className="recording-filter-chip-icon" aria-hidden="true" />
                        )}
                        {entry.name}
                      </li>
                    );
                  })}
                  {moreChip(hiddenAppCount)}
                </ul>
              )}
            </dd>
          </div>
          <div className="recording-filter-summary-row">
            <dt>{websitesMode}</dt>
            <dd>
              {captureFilter.websites.hosts.length === 0 ? (
                t('settings.recordingFilter.summary.none')
              ) : (
                <ul
                  className="recording-filter-chips"
                  aria-label={t('settings.recordingFilter.websites.listLabel')}
                >
                  {shownHosts.map((host) => (
                    <li key={host} className="recording-filter-chip">
                      <Globe className="recording-filter-chip-icon" size={14} aria-hidden="true" />
                      {host}
                    </li>
                  ))}
                  {moreChip(hiddenHostCount)}
                </ul>
              )}
            </dd>
          </div>
        </dl>
      ) : null}
    </div>
  );
}
