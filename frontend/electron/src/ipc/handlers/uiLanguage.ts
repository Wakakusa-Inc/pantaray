/**
 * ui:* IPC handlers
 *
 * 目的:
 * - UI 言語を main 側の SSOT として管理し、renderer へ提供する。
 * - 入力は unknown として受け、main 側で正規化する。
 */

import type { MainContext } from '../context';
import type { IpcRegistrar } from '../registrar';

export function registerUiLanguageHandlers(ctx: MainContext, registrar: IpcRegistrar): void {
  registrar.handle('ui:getLanguage', () => {
    return ctx.ui.getLanguage();
  });

  registrar.handle('ui:setLanguage', (_evt, lang) => {
    return ctx.ui.setLanguage(lang);
  });
}
