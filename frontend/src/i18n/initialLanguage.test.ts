import { afterEach, describe, expect, it, vi } from 'vitest';

import {
  BROWSER_UI_LANGUAGE_STORAGE_KEY,
  resolveBrowserInitialLanguage,
  resolveRendererInitialLanguage,
} from './initialLanguage';

function setElectronUi(ui: Partial<NonNullable<NonNullable<Window['electron']>['ui']>>) {
  Object.defineProperty(window, 'electron', {
    configurable: true,
    value: {
      ui: {
        getLanguage: vi.fn(),
        setLanguage: vi.fn(),
        initialLanguage: 'en',
        ...ui,
      },
    },
  });
}

describe('initialLanguage', () => {
  afterEach(() => {
    localStorage.clear();
    vi.restoreAllMocks();
    delete window.electron;
  });

  it('uses saved browser language before navigator locale in browser runtime', () => {
    localStorage.setItem(BROWSER_UI_LANGUAGE_STORAGE_KEY, 'ja');

    expect(resolveBrowserInitialLanguage()).toBe('ja');
    expect(resolveRendererInitialLanguage()).toBe('ja');
  });

  it('uses Electron preload language before browser storage', () => {
    localStorage.setItem(BROWSER_UI_LANGUAGE_STORAGE_KEY, 'ja');
    setElectronUi({ initialLanguage: 'en' });

    expect(resolveRendererInitialLanguage()).toBe('en');
  });

  it('fails fast when Electron UI exists without initial language', () => {
    setElectronUi({ initialLanguage: null });

    expect(() => resolveRendererInitialLanguage()).toThrow(
      'Electron UI initial language is missing.'
    );
  });
});
