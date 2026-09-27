import { useContext } from 'react';

import { UiLanguageContext, type UiLanguageContextValue } from './uiLanguageContextShared';

export function useI18n(): UiLanguageContextValue {
  const ctx = useContext(UiLanguageContext);
  if (!ctx) {
    throw new Error('useI18n must be used within UiLanguageProvider');
  }
  return ctx;
}
