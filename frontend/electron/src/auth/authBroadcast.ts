/**
 * Auth state broadcast（main → renderer）
 *
 * 目的:
 * - `auth:stateChanged` の送信処理を `electron/src/main.ts` から切り出し、main の責務を薄くする。
 * - 例外で main が落ちないよう best-effort で送る（既存挙動を維持）。
 */

import type { BrowserWindow } from 'electron';
import type { AuthState } from '../ipc/context';

/**
 * すべてのウィンドウへ `auth:stateChanged` を通知する。
 *
 * @param windows - 送信対象ウィンドウ一覧（通常は `BrowserWindow.getAllWindows()`）
 * @param state - auth state（SSOT の生データを許容し、最低限の shape にして送る）
 */
export function broadcastAuthStateToAllWindows(windows: BrowserWindow[], state: AuthState): void {
  try {
    const payload = {
      authStatus: state.authStatus,
      isLoggedIn: Boolean(state.isLoggedIn),
      user: state.user,
      runtimeState: state.runtimeState,
    };

    for (const win of windows) {
      try {
        if (win && !win.isDestroyed() && win.webContents) {
          win.webContents.send('auth:stateChanged', payload);
        }
      } catch {
        // no-op
      }
    }
  } catch {
    // no-op
  }
}
