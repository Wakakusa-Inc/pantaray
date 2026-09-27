import type { BrowserWindow } from 'electron';

import type { HistoryChangedPayload } from './contracts';

/** This refresh hint must not turn a committed operation into a reported failure. */
export function broadcastHistoryChanged(
  mainWindow: BrowserWindow | null,
  payload: HistoryChangedPayload
): void {
  if (!mainWindow || mainWindow.isDestroyed()) return;
  try {
    mainWindow.webContents.send('history:changed', payload);
  } catch {
    // A closing renderer can reject delivery; its next mount fetches persisted history.
    console.warn('Failed to notify history refresh.');
  }
}
