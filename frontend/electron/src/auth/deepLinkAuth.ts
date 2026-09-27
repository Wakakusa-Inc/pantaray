import type { App, BrowserWindow } from 'electron';
import type { AuthCallbackPayload, AuthCallbackResult } from './authCoordinator';

export const APP_PROTOCOL = 'pantaray';

export type DeepLinkAuthManager = {
  protocol: string;
  installAppHandlers: () => void;
  handleDeepLink: (urlStr: unknown) => void;
  onMainWindowCreated: () => void;
  handleStartupArgs: (argv: unknown[]) => void;
};

function parseAuthDeepLinkUrl(
  urlStr: unknown,
  protocol: string
): { attemptId: string; exchangeCode: string } | null {
  try {
    const url = new URL(String(urlStr || ''));
    if (url.protocol !== `${protocol}:`) return null;
    const isAuth = url.hostname === 'auth' || url.pathname === '/auth';
    if (!isAuth) return null;
    const attemptId = (url.searchParams.get('attempt_id') || '').trim();
    const exchangeCode = (url.searchParams.get('exchange_code') || '').trim();
    if (!attemptId || !exchangeCode) return null;
    return { attemptId, exchangeCode };
  } catch {
    return null;
  }
}

export function createDeepLinkAuthManager(params: {
  app: App;
  protocol?: string;
  getMainWindow: () => BrowserWindow | null;
  handleCallback: (payload: AuthCallbackPayload) => AuthCallbackResult;
}): DeepLinkAuthManager {
  const protocol = String(params.protocol || APP_PROTOCOL).trim() || APP_PROTOCOL;

  function focusMainWindow(): void {
    try {
      const win = params.getMainWindow();
      if (win && !win.isDestroyed()) {
        if (!win.isVisible()) win.show();
        win.focus();
      }
    } catch {
      // no-op
    }
  }

  function handleDeepLink(urlStr: unknown): void {
    const payload = parseAuthDeepLinkUrl(urlStr, protocol);
    if (!payload) {
      console.info('[deep-link] ignored (not an auth deep link)');
      return;
    }
    console.info('[deep-link] received auth deep link (code redacted)');
    const result = params.handleCallback({
      transport: 'deep_link',
      attemptId: payload.attemptId,
      exchangeCode: payload.exchangeCode,
    });
    if (!result.ok) {
      console.warn('[deep-link] auth callback rejected:', result.message);
    }
    focusMainWindow();
  }

  function installAppHandlers(): void {
    const app = params.app;
    const gotTheLock = app.requestSingleInstanceLock();
    if (!gotTheLock) {
      app.quit();
      return;
    }

    app.on('second-instance', (_event, commandLine) => {
      try {
        const deepLinkArg = (commandLine || []).find(
          (arg) => typeof arg === 'string' && arg.startsWith(`${protocol}://`)
        ) as string | undefined;
        if (deepLinkArg) handleDeepLink(deepLinkArg);
      } catch {
        // no-op
      }
      focusMainWindow();
    });

    app.on('open-url', (event, urlStr) => {
      try {
        event.preventDefault();
      } catch {
        // no-op
      }
      console.info('[deep-link] open-url event received');
      handleDeepLink(urlStr);
    });
  }

  function onMainWindowCreated(): void {
    focusMainWindow();
  }

  function handleStartupArgs(argv: unknown[]): void {
    try {
      const arg = (argv || []).find(
        (value) => typeof value === 'string' && value.startsWith(`${protocol}://`)
      );
      if (arg) handleDeepLink(arg);
    } catch {
      // no-op
    }
  }

  return {
    protocol,
    installAppHandlers,
    handleDeepLink,
    onMainWindowCreated,
    handleStartupArgs,
  };
}
