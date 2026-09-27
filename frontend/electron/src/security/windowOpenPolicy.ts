import type { App } from 'electron';

type LoggerLike = { warn?: (name: string, payload?: unknown) => void };

function isWebUrl(url: string): boolean {
  try {
    const { protocol } = new URL(url);
    return protocol === 'https:' || protocol === 'http:';
  } catch {
    return false;
  }
}

/**
 * A link a page opens in a new window (`target="_blank"`, `window.open`) goes to the default
 * browser. The app never creates a window for it: an Electron window has no address bar and none
 * of the user's sign-ins, and web content does not belong inside Pantaray.
 */
export function openNewWindowsInDefaultBrowser(params: {
  app: App;
  openExternal: (url: string) => Promise<void>;
  logger: LoggerLike | null;
}): void {
  params.app.on('web-contents-created', (_event, contents) => {
    contents.setWindowOpenHandler(({ url }) => {
      if (isWebUrl(url)) {
        params.openExternal(url).catch((error: unknown) => {
          params.logger?.warn?.('WINDOW_OPEN_EXTERNAL_ERR', { err: error });
        });
      }
      return { action: 'deny' };
    });
  });
}
