import type { MainContext } from '../context';
import type { IpcRegistrar } from '../registrar';

export function registerApprovalHandlers(ctx: MainContext, registrar: IpcRegistrar): void {
  registrar.handle('approval:getWorkspaceEditCommandPreference', async () => {
    return await ctx.approval.getWorkspaceEditCommandPreference();
  });

  registrar.handle('approval:setWorkspaceEditCommandPreference', async (_event, approvalMode) => {
    return await ctx.approval.setWorkspaceEditCommandPreference(approvalMode);
  });
}
