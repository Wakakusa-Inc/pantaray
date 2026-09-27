import React, { useCallback, useEffect, useMemo, useState } from 'react';

import { BROWSER_UI_LANGUAGE_STORAGE_KEY } from '@/i18n/initialLanguage';
import type { MessageKey, UiLanguage } from '@/i18n/types';
import { formatDateTime as _formatDateTime, normalizeUiLanguage, t as _t } from '@/i18n/translate';
import { UiLanguageContext, type UiLanguageContextValue } from './uiLanguageContextShared';

function getElectronUiApi() {
  if (typeof window === 'undefined') return undefined;
  return window.electron?.ui;
}

function isElectron(): boolean {
  try {
    return Boolean(getElectronUiApi());
  } catch {
    return false;
  }
}

type UiLanguageProviderProps = {
  children: React.ReactNode;
  initialLanguage: UiLanguage;
};

export const UiLanguageProvider: React.FC<UiLanguageProviderProps> = ({
  children,
  initialLanguage,
}) => {
  const [language, setLanguageState] = useState<UiLanguage>(() =>
    normalizeUiLanguage(initialLanguage)
  );

  // Electron: subscribe to SSOT updates from main. Initial language is injected before render.
  useEffect(() => {
    if (!isElectron()) {
      // Browser: keep <html lang> and persist locally.
      try {
        document.documentElement.lang = language;
      } catch {
        // no-op: DOM が利用できない環境では何もしない
      }
      try {
        localStorage.setItem(BROWSER_UI_LANGUAGE_STORAGE_KEY, language);
      } catch {
        // no-op: localStorage が利用できない環境では永続化しない
      }
      return;
    }

    let unsub: (() => void) | undefined;
    let cancelled = false;
    const electronUi = getElectronUiApi();
    try {
      unsub = electronUi?.onLanguageChanged?.((lang) => {
        if (cancelled) return;
        if (lang === 'en' || lang === 'ja') {
          setLanguageState(normalizeUiLanguage(lang));
        }
      });
    } catch {
      unsub = undefined;
    }
    void electronUi
      ?.getLanguage?.()
      .then((lang) => {
        if (cancelled) return;
        if (lang === 'en' || lang === 'ja') {
          setLanguageState(normalizeUiLanguage(lang));
        }
      })
      .catch((error: unknown) => {
        console.error('Failed to refresh Electron UI language:', error);
      });

    return () => {
      cancelled = true;
      try {
        if (unsub) unsub();
      } catch {
        // no-op: best-effort で解除する（解除失敗は致命ではない）
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Always keep <html lang> updated (Electron/Browser).
  useEffect(() => {
    try {
      document.documentElement.lang = language;
    } catch {
      // no-op: DOM が利用できない環境では何もしない
    }
  }, [language]);

  const setLanguage = useCallback(async (lang: UiLanguage) => {
    const normalized = normalizeUiLanguage(lang);
    if (isElectron()) {
      const electronUi = getElectronUiApi();
      if (!electronUi?.setLanguage) {
        throw new Error('Electron UI language API is unavailable.');
      }
      const savedLanguage = await electronUi.setLanguage(normalized);
      setLanguageState(normalizeUiLanguage(savedLanguage));
      return;
    }
    setLanguageState(normalized);
    try {
      localStorage.setItem(BROWSER_UI_LANGUAGE_STORAGE_KEY, normalized);
    } catch {
      // no-op: localStorage が利用できない環境では永続化しない
    }
  }, []);

  const value: UiLanguageContextValue = useMemo(() => {
    return {
      language,
      setLanguage,
      t: (key: MessageKey, vars?: Record<string, string | number>) => _t(language, key, vars),
      formatDateTime: (date: Date) => _formatDateTime(language, date),
    };
  }, [language, setLanguage]);

  return <UiLanguageContext.Provider value={value}>{children}</UiLanguageContext.Provider>;
};
