import type { MainContext } from '../context';
import type { IpcRegistrar } from '../registrar';
import { parseInput } from '../schemas/error';
import { GlobalShortcutAcceleratorSchema } from '../schemas/shortcut';

export function registerShortcutHandlers(ctx: MainContext, registrar: IpcRegistrar): void {
  registrar.handle('shortcut:getState', () => ctx.shortcut.getState());
  registrar.handle('shortcut:setAccelerator', (_event, accelerator) =>
    ctx.shortcut.setAccelerator(
      parseInput(GlobalShortcutAcceleratorSchema, 'shortcut:setAccelerator', accelerator)
    )
  );
}
