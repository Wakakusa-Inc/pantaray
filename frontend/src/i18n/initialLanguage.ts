import { detectBrowserUiLanguage } from './translate';
import type { UiLanguage } from './types';

export const BROWSER_UI_LANGUAGE_STORAGE_KEY = 'pantaray_ui_language';

function isUiLanguage(value: unknown): value is UiLanguage {
  return value === 'en' || value === 'ja';
}

export function resolveBrowserInitialLanguage(): UiLanguage {
  try {
    const saved = localStorage.getItem(BROWSER_UI_LANGUAGE_STORAGE_KEY);
    if (isUiLanguage(saved)) return saved;
  } catch {
    // localStorage is unavailable in some non-browser test runtimes.
  }
  return detectBrowserUiLanguage();
}

export function resolveRendererInitialLanguage(): UiLanguage {
  const electronUi = typeof window === 'undefined' ? undefined : window.electron?.ui;
  if (!electronUi) return resolveBrowserInitialLanguage();
  if (!isUiLanguage(electronUi.initialLanguage)) {
    throw new Error('Electron UI initial language is missing.');
  }
  return electronUi.initialLanguage;
}
