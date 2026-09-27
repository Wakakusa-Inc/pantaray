/**
 * open-external-url IPC handler
 *
 * 目的:
 * - renderer からの `shell.openExternal` を fail-closed で制御する。
 * - 実際のポリシー（origin 制約など）は main の security SSOT に委譲する。
 */

import type { MainContext } from '../context';
import type { IpcRegistrar } from '../registrar';

export function registerExternalUrlHandlers(ctx: MainContext, registrar: IpcRegistrar): void {
  registrar.on('open-external-url', (_evt, url) => {
    Promise.resolve()
      .then(async () => ctx.externalUrl.open(url))
      .catch(() => {
        // best-effort: 例外は main で握り、プロセスを落とさない
      });
  });
}
