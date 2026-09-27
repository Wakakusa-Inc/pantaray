import { cleanup, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { UiLanguageProvider } from './UiLanguageContext';
import { useI18n } from './useI18n';

function LanguageProbe() {
  const { language } = useI18n();
  return <div data-testid="language">{language}</div>;
}

function installElectronUi(ui: NonNullable<NonNullable<Window['electron']>['ui']>) {
  Object.defineProperty(window, 'electron', {
    configurable: true,
    value: { ui },
  });
}

describe('UiLanguageProvider', () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
    delete window.electron;
  });

  it('refreshes Electron language after subscribing so startup broadcasts cannot be missed', async () => {
    const calls: string[] = [];
    installElectronUi({
      initialLanguage: 'en',
      getLanguage: vi.fn(async () => {
        calls.push('getLanguage');
        return 'ja' as const;
      }),
      setLanguage: vi.fn(async (lang) => lang),
      onLanguageChanged: vi.fn(() => {
        calls.push('onLanguageChanged');
        return () => undefined;
      }),
    });

    render(
      <UiLanguageProvider initialLanguage="en">
        <LanguageProbe />
      </UiLanguageProvider>
    );

    expect(screen.getByTestId('language')).toHaveTextContent('en');

    await waitFor(() => {
      expect(screen.getByTestId('language')).toHaveTextContent('ja');
    });
    expect(calls).toEqual(['onLanguageChanged', 'getLanguage']);
  });
});
