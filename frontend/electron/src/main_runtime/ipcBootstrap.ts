import type { NotificationWindowApi } from '../orchestration/contracts';
import type { MainContext } from '../ipc/context';
import { buildMainContext } from '../ipc/mainContextFactory';
import { registerAllIpcHandlers, type RegisterAllResult } from '../ipc/registerAll';

export type MainContextFactoryParams = Parameters<typeof buildMainContext>[0];

export type MainIpcRuntime = RegisterAllResult & {
  context: MainContext;
};

export function wireMainIpcRuntime(params: {
  context: MainContext;
  notificationWindow: Pick<NotificationWindowApi, 'configureIpcWindowSecurity'>;
  registerHandlers: (context: MainContext) => RegisterAllResult;
}): MainIpcRuntime {
  params.notificationWindow.configureIpcWindowSecurity(params.context.security);
  const registration = params.registerHandlers(params.context);
  return { context: params.context, ...registration };
}

export function startMainIpcRuntime(params: {
  context: MainContextFactoryParams;
  notificationWindow: Pick<NotificationWindowApi, 'configureIpcWindowSecurity'>;
}): MainIpcRuntime {
  const context = buildMainContext(params.context);
  return wireMainIpcRuntime({
    context,
    notificationWindow: params.notificationWindow,
    registerHandlers: registerAllIpcHandlers,
  });
}
