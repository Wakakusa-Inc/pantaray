import { useEffect, useRef, useState, type KeyboardEvent as ReactKeyboardEvent } from 'react';

import { ShortcutKeycaps } from '@/components/shortcut/ShortcutHint';
import type { MessageKey } from '@/i18n/types';
import { shortcutAcceleratorFromKeyEvent } from '../shortcutAccelerator';

type ShortcutApi = NonNullable<NonNullable<Window['electron']>['shortcut']>;
type ShortcutState = Awaited<ReturnType<ShortcutApi['getState']>>;
type ShortcutFailureNotice =
  | ShortcutState['failure']
  | 'load_failed'
  | 'initial_registration_unavailable'
  | 'initial_persistence_failed';
type ShortcutSectionProps = {
  t: (key: MessageKey, vars?: Record<string, string | number>) => string;
};

const NOTICE_KEYS: Readonly<
  Record<Exclude<'loading' | 'saved' | ShortcutFailureNotice, null>, MessageKey>
> = {
  loading: 'settings.shortcut.loading',
  saved: 'settings.shortcut.saved',
  load_failed: 'settings.shortcut.loadFailed',
  settings_unreadable: 'settings.shortcut.settingsUnreadable',
  initial_registration_unavailable: 'settings.shortcut.initialRegistrationUnavailable',
  initial_persistence_failed: 'settings.shortcut.initialPersistenceFailed',
  registration_unavailable: 'settings.shortcut.registrationUnavailable',
  persistence_failed: 'settings.shortcut.persistenceFailed',
};

function noticeForInitialFailure(failure: ShortcutState['failure']): ShortcutFailureNotice {
  if (failure === 'settings_unreadable') return 'settings_unreadable';
  if (failure === 'registration_unavailable') return 'initial_registration_unavailable';
  if (failure === 'persistence_failed') return 'initial_persistence_failed';
  return null;
}

export function ShortcutSection({ t }: ShortcutSectionProps) {
  const [shortcutState, setShortcutState] = useState<ShortcutState | null>(null);
  const [notice, setNotice] = useState<'loading' | 'saved' | null>('loading');
  const [failureNotice, setFailureNotice] = useState<ShortcutFailureNotice>(null);
  const [isRecording, setIsRecording] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const recordButtonRef = useRef<HTMLButtonElement>(null);
  const isMac = window.electron?.process.platform === 'darwin';
  useEffect(() => {
    let cancelled = false;
    const loadShortcut = async () => {
      try {
        const shortcutApi = window.electron?.shortcut;
        if (!shortcutApi) throw new Error('Shortcut settings bridge is unavailable.');
        const state = await shortcutApi.getState();
        if (cancelled) return;
        setShortcutState(state);
        setNotice(null);
        setFailureNotice(noticeForInitialFailure(state.failure));
      } catch {
        if (cancelled) return;
        setShortcutState(null);
        setNotice(null);
        setFailureNotice('load_failed');
      }
    };
    void loadShortcut();
    return () => {
      cancelled = true;
    };
  }, []);

  const saveAccelerator = async (accelerator: string) => {
    if (isSaving) return;
    setIsRecording(false);
    setIsSaving(true);
    setNotice(null);
    try {
      const shortcutApi = window.electron?.shortcut;
      if (!shortcutApi) throw new Error('Shortcut settings bridge is unavailable.');
      const result = await shortcutApi.setAccelerator(accelerator);
      if (!result.ok) {
        setShortcutState(result.state);
        setFailureNotice(noticeForInitialFailure(result.state.failure) ?? result.reason);
        return;
      }
      setShortcutState(result.state);
      setFailureNotice(null);
      setNotice('saved');
    } catch {
      setFailureNotice('persistence_failed');
    } finally {
      setIsSaving(false);
      setTimeout(() => recordButtonRef.current?.focus(), 0);
    }
  };

  const handleKeyDown = (event: ReactKeyboardEvent<HTMLButtonElement>) => {
    if (!isRecording) return;
    const accelerator = shortcutAcceleratorFromKeyEvent(event.nativeEvent, isMac);
    if (!accelerator) return;
    event.preventDefault();
    void saveAccelerator(accelerator);
  };

  const accelerator = shortcutState?.accelerator ?? null;
  const noticeText = notice ? t(NOTICE_KEYS[notice]) : '';
  const failureText = failureNotice ? t(NOTICE_KEYS[failureNotice]) : '';
  return (
    <div className="dashboard-section execution-settings-section">
      <h3 className="dashboard-section-title">{t('settings.shortcut.title')}</h3>
      <div className="settings-control-row">
        <div className="settings-control-copy">
          <div className="settings-control-title">{t('settings.shortcut.controlTitle')}</div>
          <p className="dashboard-section-description settings-control-description settings-control-description--compact">
            {t('settings.shortcut.description')}
          </p>
        </div>
        <div className="settings-shortcut-actions">
          {accelerator ? (
            <ShortcutKeycaps accelerator={accelerator} t={t} />
          ) : (
            <span className="settings-section-status">{t('settings.shortcut.unavailable')}</span>
          )}
          <button
            ref={recordButtonRef}
            type="button"
            className="settings-action-button"
            disabled={shortcutState === null || isSaving}
            onClick={() => {
              setIsRecording(true);
              setNotice(null);
            }}
            onKeyDown={handleKeyDown}
          >
            {isRecording ? t('settings.shortcut.recordingButton') : t('settings.shortcut.change')}
          </button>
          {isRecording ? (
            <button
              type="button"
              className="settings-action-button"
              onClick={() => {
                setIsRecording(false);
                recordButtonRef.current?.focus();
              }}
            >
              {t('settings.shortcut.cancel')}
            </button>
          ) : null}
        </div>
      </div>
      {noticeText ? (
        <p className="settings-section-status" aria-live="polite" aria-atomic="true">
          {noticeText}
        </p>
      ) : null}
      {isRecording ? (
        <p className="settings-section-status" aria-live="polite">
          {t('settings.shortcut.recording', { alt: isMac ? 'Option' : 'Alt' })}
        </p>
      ) : null}
      {failureText ? (
        <p className="settings-section-status settings-section-error" aria-live="polite">
          {failureText}
        </p>
      ) : null}
    </div>
  );
}
