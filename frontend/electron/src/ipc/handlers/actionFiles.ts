import type { MainContext } from '../context';
import type { IpcRegistrar } from '../registrar';
import { parseInput } from '../schemas/error';
import { ActionFileOpenInputSchema } from '../schemas/actionFiles';

export function registerActionFileHandlers(ctx: MainContext, registrar: IpcRegistrar): void {
  registrar.handle('actionFile:open', async (_event, params) => {
    const parsed = parseInput(ActionFileOpenInputSchema, 'actionFile:open', params);
    ctx.actionFiles.open(parsed);
  });
}
