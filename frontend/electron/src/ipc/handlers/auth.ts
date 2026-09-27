/**
 * auth:* IPC handlers
 *
 * 目的:
 * - 認証状態の参照/操作を renderer へ提供する（トークンは返さない）。
 * - Browser login（PKCE attempt）は verifier を main に保持したまま、必要情報のみ renderer に返す。
 */

import type { MainContext } from '../context';
import type { IpcRegistrar } from '../registrar';

export function registerAuthHandlers(ctx: MainContext, registrar: IpcRegistrar): void {
  registrar.handle('auth:confirmationComplete', () => {
    try {
      ctx.windows.showMainRoute('/login');
    } catch {
      // no-op
    }
    return true;
  });

  registrar.handle('auth:saveLoginState', (_event, isLoggedIn) => {
    try {
      ctx.auth.saveLoginState(Boolean(isLoggedIn));
    } catch {
      // no-op
    }
    return { success: true };
  });

  registrar.handle('auth:getState', () => {
    try {
      return ctx.auth.getState();
    } catch {
      return {
        isLoggedIn: false,
        user: null,
        runtimeState: { status: 'unknown', message: null },
      };
    }
  });

  registrar.handle('auth:signOut', async () => {
    try {
      return await ctx.auth.signOut();
    } catch (e) {
      return { ok: false, error: e instanceof Error ? e.message : String(e) };
    }
  });

  registrar.handle('auth:startBrowserLogin', async (_event, route) => {
    try {
      return await ctx.auth.startBrowserLogin(route);
    } catch (e) {
      return { ok: false, error: e instanceof Error ? e.message : String(e) };
    }
  });
}
