import type { BrowserWindow } from 'electron';

export type RestorableWindow = Pick<
  BrowserWindow,
  'focus' | 'isDestroyed' | 'isMinimized' | 'isVisible' | 'restore' | 'show'
>;

export function restoreAndFocusWindow(win: RestorableWindow | null | undefined): boolean {
  if (!win || win.isDestroyed()) {
    return false;
  }

  if (win.isMinimized()) {
    win.restore();
  }

  if (!win.isVisible()) {
    win.show();
  }

  win.focus();
  return true;
}

/**
 * Puts the main window in front of the user, creating it when there is none.
 *
 * On macOS the app keeps running after its window is closed, so both Dock
 * activation and anything that has something to show the user must be able to
 * bring a window back rather than assume one exists.
 *
 * Returns the window that was brought forward, or `null` when one was created:
 * a window that already existed is loaded and can be told what to show, while a
 * created one shows it as it loads.
 */
export function ensureMainWindowFocused<W extends RestorableWindow>(params: {
  getMainWindow: () => W | null;
  createMainWindow: () => void;
}): W | null {
  const existing = params.getMainWindow();
  if (restoreAndFocusWindow(existing)) return existing;
  params.createMainWindow();
  return null;
}
