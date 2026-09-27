import { createContext } from 'react';

import type { MessageKey, UiLanguage } from '@/i18n/types';

export type UiLanguageContextValue = {
  language: UiLanguage;
  setLanguage: (lang: UiLanguage) => Promise<void>;
  t: (key: MessageKey, vars?: Record<string, string | number>) => string;
  formatDateTime: (date: Date) => string;
};

export const UiLanguageContext = createContext<UiLanguageContextValue | null>(null);
