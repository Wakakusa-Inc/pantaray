import { MESSAGES } from './messages';
import type { MessageKey, UiLanguage } from './types';

export function normalizeUiLanguage(value: unknown): UiLanguage {
  return value === 'ja' ? 'ja' : 'en';
}

export function getLocaleForUiLanguage(language: UiLanguage): string {
  return language === 'ja' ? 'ja-JP' : 'en-US';
}

export function detectBrowserUiLanguage(): UiLanguage {
  try {
    const langs = Array.isArray(navigator.languages) ? navigator.languages : [];
    const primary = (langs[0] || navigator.language || '').toLowerCase();
    if (primary.startsWith('ja')) return 'ja';
  } catch {
    // no-op: navigator が利用できない環境ではデフォルトへフォールバック
  }
  return 'en';
}

export function t(
  language: UiLanguage,
  key: MessageKey,
  vars?: Record<string, string | number>
): string {
  const dict = MESSAGES[language] as Record<string, string>;
  const fallback = MESSAGES.en as Record<string, string>;
  const template = dict[key] ?? fallback[key] ?? String(key);
  if (!vars) return template;
  return template.replace(/\{(\w+)\}/g, (_m, name: string) => {
    const v = vars[name];
    return v === undefined || v === null ? '' : String(v);
  });
}

export function formatDateTime(language: UiLanguage, date: Date): string {
  const locale = getLocaleForUiLanguage(language);
  return new Intl.DateTimeFormat(locale, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  }).format(date);
}
