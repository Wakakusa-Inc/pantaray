import { useEffect, useRef, useState } from 'react';
import { Globe, X } from 'lucide-react';

import { captureAppKey, findInstalledApp, parseWebsiteHost } from '../model';
import type {
  CaptureAppEntry,
  CaptureFilter,
  CaptureFilterMode,
  InstalledApp,
  Translate,
} from '../types';
import { AppPickerPopover } from './AppPickerPopover';
import './recordingFilter.css';

/** Only these two browsers are governed by the recorder's website rules. */

interface RecordingFilterDialogProps {
  filter: CaptureFilter;
  installedApps: InstalledApp[];
  installedAppsError: string | null;
  isLoadingInstalledApps: boolean;
  isOpen: boolean;
  saveError: string | null;
  t: Translate;
  onCancel: () => void;
  onSubmit: (filter: CaptureFilter) => void;
}

export function RecordingFilterDialog(props: RecordingFilterDialogProps) {
  const { filter, isOpen, onCancel, onSubmit, t } = props;
  const dialogRef = useRef<HTMLDialogElement>(null);
  const addAppButtonRef = useRef<HTMLButtonElement>(null);
  const [draft, setDraft] = useState<CaptureFilter>(filter);
  const [isPickerOpen, setPickerOpen] = useState(false);
  const [hostDraft, setHostDraft] = useState<string | null>(null);
  const [hostError, setHostError] = useState<string | null>(null);

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    if (isOpen && !dialog.open) {
      setDraft(filter);
      setPickerOpen(false);
      setHostDraft(null);
      setHostError(null);
      dialog.showModal();
    } else if (!isOpen && dialog.open) {
      dialog.close();
    }
    // `filter` is the starting point captured when the dialog opens, not a live input.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isOpen]);

  const setAppsMode = (mode: CaptureFilterMode) =>
    setDraft((current) => ({ ...current, apps: { ...current.apps, mode } }));
  const setWebsitesMode = (mode: CaptureFilterMode) =>
    setDraft((current) => ({ ...current, websites: { ...current.websites, mode } }));

  const addApp = (app: InstalledApp) =>
    setDraft((current) => {
      const entry: CaptureAppEntry = { name: app.name, bundleId: app.bundleId };
      if (current.apps.entries.some((listed) => captureAppKey(listed) === captureAppKey(entry))) {
        return current;
      }
      return { ...current, apps: { ...current.apps, entries: [...current.apps.entries, entry] } };
    });

  const removeApp = (key: string) =>
    setDraft((current) => ({
      ...current,
      apps: {
        ...current.apps,
        entries: current.apps.entries.filter((entry) => captureAppKey(entry) !== key),
      },
    }));

  const removeHost = (host: string) =>
    setDraft((current) => ({
      ...current,
      websites: {
        ...current.websites,
        hosts: current.websites.hosts.filter((listed) => listed !== host),
      },
    }));

  const saveHost = () => {
    const parsed = parseWebsiteHost(hostDraft ?? '');
    if (!parsed.ok) {
      setHostError(t('settings.recordingFilter.websites.invalidHost'));
      return;
    }
    setDraft((current) => ({
      ...current,
      websites: {
        ...current.websites,
        hosts: current.websites.hosts.includes(parsed.host)
          ? current.websites.hosts
          : [...current.websites.hosts, parsed.host],
      },
    }));
    setHostDraft('');
    setHostError(null);
  };

  return (
    <dialog
      ref={dialogRef}
      className="recording-filter-dialog"
      aria-labelledby="recording-filter-dialog-title"
      onCancel={(event) => {
        event.preventDefault();
        onCancel();
      }}
    >
      <h3 id="recording-filter-dialog-title">{t('settings.recordingFilter.title')}</h3>
      <p className="recording-filter-dialog-description">
        {t('settings.recordingFilter.description')}
      </p>

      <div className="recording-filter-columns">
        <section className="recording-filter-column">
          <select
            className="recording-filter-mode"
            aria-label={t('settings.recordingFilter.apps.modeLabel')}
            value={draft.apps.mode}
            onChange={(event) => setAppsMode(event.target.value as CaptureFilterMode)}
          >
            <option value="exclude">{t('settings.recordingFilter.apps.mode.exclude')}</option>
            <option value="include_only">
              {t('settings.recordingFilter.apps.mode.includeOnly')}
            </option>
          </select>
          <ul
            className="recording-filter-list"
            aria-label={t('settings.recordingFilter.apps.listLabel')}
          >
            {draft.apps.entries.length === 0 ? (
              <li className="recording-filter-empty">
                {t(
                  draft.apps.mode === 'exclude'
                    ? 'settings.recordingFilter.apps.emptyExclude'
                    : 'settings.recordingFilter.apps.emptyIncludeOnly'
                )}
              </li>
            ) : (
              draft.apps.entries.map((entry) => {
                const key = captureAppKey(entry);
                const installed = findInstalledApp(props.installedApps, entry);
                // Only an answered enumeration proves the app is gone: until then the
                // row is simply waiting for icons, and an error says nothing about it.
                const isMissing =
                  !installed && !props.isLoadingInstalledApps && props.installedAppsError === null;
                return (
                  <li key={key} className="recording-filter-row">
                    {installed?.iconDataUrl ? (
                      <img
                        className="recording-filter-row-icon"
                        src={installed.iconDataUrl}
                        alt=""
                      />
                    ) : isMissing ? (
                      <span
                        className="recording-filter-row-icon"
                        role="img"
                        title={t('settings.recordingFilter.apps.notInstalled')}
                        aria-label={t('settings.recordingFilter.apps.notInstalled')}
                      />
                    ) : (
                      <span className="recording-filter-row-icon" aria-hidden="true" />
                    )}
                    <span className="recording-filter-row-name">{entry.name}</span>
                    <button
                      type="button"
                      className="recording-filter-remove"
                      aria-label={t('settings.recordingFilter.removeEntry', { name: entry.name })}
                      onClick={() => removeApp(key)}
                    >
                      <X size={14} aria-hidden="true" />
                    </button>
                  </li>
                );
              })
            )}
          </ul>
          <div className="recording-filter-add">
            <button
              ref={addAppButtonRef}
              type="button"
              className="settings-action-button"
              aria-expanded={isPickerOpen}
              onClick={() => setPickerOpen((open) => !open)}
            >
              {t('settings.recordingFilter.apps.add')}
            </button>
            {isPickerOpen ? (
              <AppPickerPopover
                installedApps={props.installedApps}
                isLoading={props.isLoadingInstalledApps}
                listed={draft.apps.entries}
                loadError={props.installedAppsError}
                triggerRef={addAppButtonRef}
                t={t}
                onDismiss={() => setPickerOpen(false)}
                onSelect={addApp}
              />
            ) : null}
          </div>
        </section>

        <section className="recording-filter-column">
          <select
            className="recording-filter-mode"
            aria-label={t('settings.recordingFilter.websites.modeLabel')}
            value={draft.websites.mode}
            onChange={(event) => setWebsitesMode(event.target.value as CaptureFilterMode)}
          >
            <option value="exclude">{t('settings.recordingFilter.websites.mode.exclude')}</option>
            <option value="include_only">
              {t('settings.recordingFilter.websites.mode.includeOnly')}
            </option>
          </select>
          <ul
            className="recording-filter-list"
            aria-label={t('settings.recordingFilter.websites.listLabel')}
          >
            {draft.websites.hosts.length === 0 ? (
              <li className="recording-filter-empty">
                {t(
                  draft.websites.mode === 'exclude'
                    ? 'settings.recordingFilter.websites.emptyExclude'
                    : 'settings.recordingFilter.websites.emptyIncludeOnly'
                )}
              </li>
            ) : (
              draft.websites.hosts.map((host) => (
                <li key={host} className="recording-filter-row">
                  <Globe className="recording-filter-row-icon" size={18} aria-hidden="true" />
                  <span className="recording-filter-row-text">
                    <span className="recording-filter-row-name">{host}</span>
                  </span>
                  <button
                    type="button"
                    className="recording-filter-remove"
                    aria-label={t('settings.recordingFilter.removeEntry', { name: host })}
                    onClick={() => removeHost(host)}
                  >
                    <X size={14} aria-hidden="true" />
                  </button>
                </li>
              ))
            )}
          </ul>
          {hostDraft === null ? (
            <div className="recording-filter-add">
              <button
                type="button"
                className="settings-action-button"
                onClick={() => setHostDraft('')}
              >
                {t('settings.recordingFilter.websites.add')}
              </button>
            </div>
          ) : (
            <form
              className="recording-filter-host-form"
              onSubmit={(event) => {
                event.preventDefault();
                saveHost();
              }}
            >
              <input
                autoFocus
                className="recording-filter-host-input"
                placeholder="example.com"
                aria-label={t('settings.recordingFilter.websites.inputLabel')}
                aria-invalid={hostError !== null}
                aria-describedby={hostError ? 'recording-filter-host-error' : undefined}
                value={hostDraft}
                onChange={(event) => {
                  setHostDraft(event.target.value);
                  setHostError(null);
                }}
              />
              <button type="submit" className="settings-action-button" disabled={!hostDraft.trim()}>
                {t('common.save')}
              </button>
            </form>
          )}
          {hostError ? (
            <p id="recording-filter-host-error" className="recording-filter-empty" role="alert">
              {hostError}
            </p>
          ) : null}
        </section>
      </div>

      <p className="recording-filter-note">{t('settings.recordingFilter.privacyNote')}</p>
      {props.saveError ? (
        <p className="recording-filter-note settings-section-error" role="alert">
          {props.saveError}
        </p>
      ) : null}

      <div className="recording-filter-footer">
        <button type="button" className="settings-action-button" onClick={onCancel}>
          {t('common.cancel')}
        </button>
        <button type="button" className="settings-action-button" onClick={() => onSubmit(draft)}>
          {t('settings.recordingFilter.submit')}
        </button>
      </div>
    </dialog>
  );
}
