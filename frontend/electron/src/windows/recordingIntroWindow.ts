import type { WebContents } from 'electron';

import { ensureMainWindowFocused, type RestorableWindow } from './windowVisibility';

type MainWindow = RestorableWindow & { webContents: Pick<WebContents, 'send'> };

/**
 * Brings the main window — the one window the recording screen lives in — in
 * front of the user, so a conversation the permission gate stopped can ask for
 * the permissions it needs.
 *
 * The screen opens off the gate state the renderer reads, never off a state main
 * pushes: the renderer re-reads it when it mounts and whenever this window is
 * focused. A window that is already in front receives no focus event from
 * `focus()`, so it is told to re-read the gate now. A window created here reads
 * it as it mounts, which is why nothing is sent to it.
 */
export function presentRecordingIntro(params: {
  getMainWindow: () => MainWindow | null;
  createMainWindow: () => void;
}): void {
  ensureMainWindowFocused(params)?.webContents.send('recording:gateStateChanged');
}
