import type { App, Dialog } from 'electron';

import type { UiLanguage } from '../ipc/context';
import { getStartupDialogCopy } from '../ui/mainProcessCopy';

type LoggerLike = {
  error?: (name: string, payload?: unknown) => void;
};

type StartupFailureKind = 'runtime-config' | 'startup';

function errorDetail(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

export function reportFatalStartupFailure(params: {
  app: App;
  dialog: Pick<Dialog, 'showErrorBox'>;
  error: unknown;
  getUiLanguage: () => UiLanguage;
  kind: StartupFailureKind;
  logger: LoggerLike | null;
  stage: string;
  quitPackagedApp: boolean;
}): void {
  const stack = params.error instanceof Error ? params.error.stack : null;
  params.logger?.error?.('APP_STARTUP_ERR', {
    stage: params.stage,
    err: params.error,
    stack,
  });

  const text = getStartupDialogCopy(params.getUiLanguage());
  const detail = errorDetail(params.error);
  try {
    if (params.kind === 'runtime-config') {
      params.dialog.showErrorBox(text.runtimeConfigTitle, text.runtimeConfigBody(detail));
    } else {
      params.dialog.showErrorBox(text.startupTitle, text.startupBody(detail));
    }
  } catch (dialogError) {
    params.logger?.error?.('APP_STARTUP_DIALOG_ERR', {
      stage: params.stage,
      err: dialogError,
    });
  }

  if (params.quitPackagedApp && params.app.isPackaged) {
    params.app.quit();
  }
}
