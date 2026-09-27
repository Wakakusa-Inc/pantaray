/**
 * window:* IPC handlers
 *
 * 目的:
 * - renderer からの window 操作を最小権限で提供する。
 * - 既存挙動（mainWindow が無い場合の安全側 fallback）を維持する。
 */

import type { MainContext } from '../context';
import type { IpcRegistrar } from '../registrar';

export function registerWindowHandlers(ctx: MainContext, registrar: IpcRegistrar): void {
  registrar.handle('window:getPosition', () => {
    const win = ctx.windows.getMainWindow();
    if (!win || (typeof win.isDestroyed === 'function' && win.isDestroyed())) {
      return { x: 0, y: 0 };
    }
    const [x, y] = win.getPosition();
    return { x, y };
  });

  registrar.handle('window:move', (_evt, position) => {
    const win = ctx.windows.getMainWindow();
    if (!win || (typeof win.isDestroyed === 'function' && win.isDestroyed())) return false;
    const p = position as { x?: unknown; y?: unknown } | null;
    if (!p || typeof p.x !== 'number' || typeof p.y !== 'number') return false;
    win.setPosition(p.x, p.y);
    return true;
  });

  registrar.handle('window:close', () => {
    const win = ctx.windows.getMainWindow();
    if (win && !(typeof win.isDestroyed === 'function' && win.isDestroyed())) {
      try {
        win.close();
      } catch {
        // no-op
      }
    }
    return true;
  });
}
