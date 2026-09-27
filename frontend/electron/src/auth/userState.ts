/**
 * User state persistence（legacy）
 *
 * 目的:
 * - `electron/src/main.ts` からユーザー状態（isLoggedIn）の永続化処理を切り出し、main の責務を薄くする。
 * - 既存の保存形式（`user-state.json`）と挙動を維持する。
 */

import fs from 'fs';
import path from 'path';

/**
 * `user-state.json` へログイン状態を保存する（best-effort）。
 *
 * @param userDataDir - `app.getPath('userData')`
 * @param isLoggedIn - ログイン状態
 */
export function saveUserState(userDataDir: string, isLoggedIn: boolean): void {
  try {
    const p = path.join(String(userDataDir || '').trim(), 'user-state.json');
    fs.writeFileSync(p, JSON.stringify({ isLoggedIn }));
  } catch (error) {
    console.error('ユーザー状態の保存に失敗しました:', error);
  }
}
