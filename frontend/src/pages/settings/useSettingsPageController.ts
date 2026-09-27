import { useCallback, useEffect, useRef, useState } from 'react';

import { useI18n } from '@/context/useI18n';
import type { CapturePrivacySettings } from '../../../electron/src/privacy/capturePrivacy';
import type { MessageKey } from '@/i18n/types';

import {
  DEFAULT_CAPTURE_FILTER,
  buildCaptureSettingsPayload,
  getIdeSensitivePresets,
  normalizeCaptureFilterForUi,
  normalizeIdeFileRulesForUi,
} from './model';
import { useScreenshotCaptureStatus } from './useScreenshotCaptureStatus';
import { useCaptureEditingSession } from './useCaptureEditingSession';
import type { CaptureFilter, IdeFileRules, InstalledApp } from './types';

export function useSettingsPageController() {
  const { t } = useI18n();
  const settingsRevision = useRef(0);
  const ideWriteId = useRef(0);
  const notifiedSettings = useRef<CapturePrivacySettings | null>(null);
  const [captureFilter, setCaptureFilter] = useState<CaptureFilter>(DEFAULT_CAPTURE_FILTER);
  const [isLoadingCaptureFilter, setIsLoadingCaptureFilter] = useState<boolean>(true);
  const [captureFilterError, setCaptureFilterError] = useState<MessageKey | null>(null);
  const {
    isOpen: isFilterDialogOpen,
    open: openEditor,
    close: closeEditor,
  } = useCaptureEditingSession();
  const [installedApps, setInstalledApps] = useState<InstalledApp[]>([]);
  const [isLoadingInstalledApps, setIsLoadingInstalledApps] = useState<boolean>(false);
  const [installedAppsError, setInstalledAppsError] = useState<MessageKey | null>(null);
  const [ideFileRules, setIdeFileRules] = useState<IdeFileRules | null>(null);
  const [isLoadingIdeFileRules, setIsLoadingIdeFileRules] = useState<boolean>(true);
  const [ideFileRulesError, setIdeFileRulesError] = useState<MessageKey | null>(null);
  const screenshotCapture = useScreenshotCaptureStatus();

  const hasCaptureSettings = ideFileRules !== null;
  const applySettings = useCallback((settings: CapturePrivacySettings) => {
    setCaptureFilter(normalizeCaptureFilterForUi(settings));
    setIdeFileRules(normalizeIdeFileRulesForUi(settings.ideFileRules));
    setCaptureFilterError(null);
    setIdeFileRulesError(null);
    setIsLoadingCaptureFilter(false);
    setIsLoadingIdeFileRules(false);
  }, []);

  useEffect(() => {
    let active = true;
    let unsubscribe: (() => void) | undefined;
    const fetchCaptureSettings = async () => {
      const revision = settingsRevision.current;
      try {
        const privacy = window.electron!.privacy!;
        unsubscribe = privacy.onCaptureSettingsUpdated?.((settings) => {
          if (!active) return;
          settingsRevision.current += 1;
          notifiedSettings.current = settings;
          applySettings(settings);
        });
        const settings = await privacy.getCaptureSettings();
        if (!active || revision !== settingsRevision.current) return;
        applySettings(settings);
      } catch {
        if (!active || revision !== settingsRevision.current) return;
        console.error('Failed to load recording settings');
        setCaptureFilterError('settings.recordingFilter.loadFailed');
        setIdeFileRulesError('settings.ideFileRules.loadFailed');
        setIsLoadingCaptureFilter(false);
        setIsLoadingIdeFileRules(false);
      }
    };
    void fetchCaptureSettings();
    return () => {
      active = false;
      unsubscribe?.();
    };
  }, [applySettings]);

  const loadInstalledApps = useCallback(async () => {
    try {
      setIsLoadingInstalledApps(true);
      setInstalledAppsError(null);
      setInstalledApps(await window.electron!.privacy!.listInstalledApps());
    } catch {
      console.error('Failed to list installed apps');
      setInstalledAppsError('settings.recordingFilter.apps.loadFailed');
    } finally {
      setIsLoadingInstalledApps(false);
    }
  }, []);

  /**
   * The summary draws every listed app with its own icon, and an icon only reaches
   * the renderer through this enumeration. Nothing beyond the apps the user already
   * chose is put on screen by it, unlike the picker, which stays behind the pause.
   * A filter that lists no app needs no icon, so the default setup never scans.
   */
  const hasListedApps = hasCaptureSettings && captureFilter.apps.entries.length > 0;
  useEffect(() => {
    if (!hasListedApps) return;
    void loadInstalledApps();
  }, [hasListedApps, loadInstalledApps]);

  /**
   * Editing pauses every app while the dialog is open, so nothing typed into the
   * website field or shown by the app picker can end up in the recording. The dialog
   * therefore opens only once the pause is confirmed; if it fails, the editor stays
   * closed and the section reports the failure.
   */
  const openFilterDialog = useCallback(async () => {
    if (!hasCaptureSettings) return;
    try {
      setCaptureFilterError(null);
      if (!(await openEditor())) return;
    } catch {
      console.error('Failed to enter capture editing mode');
      setCaptureFilterError('settings.recordingFilter.pauseFailed');
      return;
    }
    // Every open enumerates again: an app installed since the last open must be
    // offerable, or the user cannot exclude it until the next restart.
    if (isLoadingInstalledApps) return;
    await loadInstalledApps();
  }, [hasCaptureSettings, isLoadingInstalledApps, loadInstalledApps, openEditor]);

  /**
   * Leaving editing mode restarts the recorder, so a failure means recording is off
   * while the stored preference says it is on. The editor stays open with the error
   * rather than closing onto a settings page that looks like recording is running.
   */
  const closeFilterDialog = useCallback(async () => {
    try {
      await closeEditor();
    } catch {
      console.error('Failed to exit capture editing mode');
      setCaptureFilterError('settings.recordingFilter.resumeFailed');
    }
  }, [closeEditor]);

  const saveCaptureFilter = useCallback(
    async (nextFilter: CaptureFilter) => {
      if (!hasCaptureSettings) return;
      const revision = settingsRevision.current;
      try {
        setCaptureFilterError(null);
        const saved = await window.electron!.privacy!.updateCaptureSettings(
          buildCaptureSettingsPayload(nextFilter)
        );
        if (revision === settingsRevision.current) applySettings(saved);
        await closeFilterDialog();
      } catch {
        // A notification confirms persistence even if the subsequent IPC reply is lost.
        // An unrelated notification must not turn a failed write into success.
        if (
          revision !== settingsRevision.current &&
          notifiedSettings.current &&
          JSON.stringify(normalizeCaptureFilterForUi(notifiedSettings.current)) ===
            JSON.stringify(normalizeCaptureFilterForUi(nextFilter))
        ) {
          await closeFilterDialog();
          return;
        }
        console.error('Failed to save recording filter');
        setCaptureFilterError('settings.recordingFilter.saveFailed');
      }
    },
    [applySettings, closeFilterDialog, hasCaptureSettings]
  );

  const setIdeSensitivePresetEnv = async (value: boolean) => {
    if (!ideFileRules) return;
    const revision = settingsRevision.current;
    const writeId = ++ideWriteId.current;
    const next = {
      ...ideFileRules,
      mode: value ? ('on' as const) : ('off' as const),
      sensitivePresets: { blockEnvFiles: value },
    };
    try {
      setIdeFileRulesError(null);
      const saved = await window.electron!.privacy!.updateIdeFileRules(next);
      if (writeId !== ideWriteId.current) return;
      if (revision === settingsRevision.current) setIdeFileRules(normalizeIdeFileRulesForUi(saved));
    } catch {
      if (writeId !== ideWriteId.current) return;
      const confirmed = notifiedSettings.current?.ideFileRules;
      if (
        revision !== settingsRevision.current &&
        confirmed?.mode === next.mode &&
        confirmed.onFileNameUnavailable === next.onFileNameUnavailable &&
        confirmed.sensitivePresets.blockEnvFiles === value
      )
        return;
      console.error('Failed to persist IDE file rules');
      setIdeFileRulesError('settings.ideFileRules.saveFailed');
    }
  };

  return {
    captureFilter,
    hasCaptureSettings,
    captureFilterError: captureFilterError && t(captureFilterError),
    closeFilterDialog,
    ideFileRules,
    ideFileRulesError: ideFileRulesError && t(ideFileRulesError),
    ideSensitivePresets: getIdeSensitivePresets(ideFileRules),
    installedApps,
    installedAppsError: installedAppsError && t(installedAppsError),
    isCapturingScreenshots: screenshotCapture.isCapturingScreenshots,
    captureStatusUnavailable: screenshotCapture.captureStatusUnavailable,
    isFilterDialogOpen,
    isLoadingCaptureFilter,
    isLoadingIdeFileRules,
    isLoadingInstalledApps,
    isProcessing: screenshotCapture.isProcessing,
    isScreenshotCaptureAvailable: screenshotCapture.isScreenshotCaptureAvailable,
    openFilterDialog,
    saveCaptureFilter,
    setIdeSensitivePresetEnv,
    setScreenshotsEnabled: screenshotCapture.setScreenshotsEnabled,
  };
}
