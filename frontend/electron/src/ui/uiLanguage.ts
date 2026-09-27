/**
 * UI language (SSOT)
 *
 * 目的:
 * - UI言語設定を main 側でSSOTとして管理し、renderer へ配信する。
 * - main_legacy.js から切り出して責務境界（ui）を明確にする。
 */

import fs from 'fs';
import path from 'path';

export type UiLanguage = 'en' | 'ja';

export function normalizeUiLanguage(value: unknown): UiLanguage {
  return value === 'ja' ? 'ja' : 'en';
}

export function defaultUiLanguage(locale: unknown): UiLanguage {
  return String(locale || '')
    .toLowerCase()
    .startsWith('ja')
    ? 'ja'
    : 'en';
}

export function loadUiLanguage(settingsPath: string, locale: unknown): UiLanguage {
  if (!fs.existsSync(settingsPath)) {
    return defaultUiLanguage(locale);
  }
  const raw = fs.readFileSync(settingsPath, 'utf8');
  const parsed = JSON.parse(raw);
  const lang = parsed?.ui_language;
  if (lang === 'en' || lang === 'ja') return lang;
  throw new Error(`Invalid UI language settings: ${settingsPath}`);
}

export function saveUiLanguage(settingsPath: string, lang: UiLanguage): void {
  fs.mkdirSync(path.dirname(settingsPath), { recursive: true });
  fs.writeFileSync(settingsPath, JSON.stringify({ ui_language: lang }, null, 2));
}

export function broadcastUiLanguage(
  windows: Array<{
    isDestroyed?: () => boolean;
    webContents?: { send: (channel: string, payload: unknown) => void };
  }>,
  lang: UiLanguage
): void {
  const normalized = normalizeUiLanguage(lang);
  for (const win of windows) {
    try {
      if (win && typeof win.isDestroyed === 'function' && win.isDestroyed()) continue;
      win?.webContents?.send?.('ui:languageChanged', normalized);
    } catch {
      // best-effort
    }
  }
}
