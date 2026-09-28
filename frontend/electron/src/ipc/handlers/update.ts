import type { MainContext } from '../context';
import type { IpcRegistrar } from '../registrar';

export function registerUpdateHandlers(ctx: MainContext, registrar: IpcRegistrar): void {
  registrar.handle('update:getReadyNotice', () => ctx.update.getReadyNotice());
  registrar.handle('update:restartToUpdate', () => ctx.update.restartToUpdate());
}
