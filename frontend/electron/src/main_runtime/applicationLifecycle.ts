import path from 'path';

import type { App } from 'electron';

type AppWithQuitFlag = App & { isQuitting?: boolean };

type LoggerLike = {
  error?: (name: string, payload?: unknown) => void;
  warn?: (name: string, payload?: unknown) => void;
};

function registerProtocol(params: {
  app: App;
  protocol: string;
  argv: string[];
  execPath: string;
  isDefaultApp: boolean;
}): void {
  if (!params.isDefaultApp) {
    params.app.setAsDefaultProtocolClient(params.protocol);
    return;
  }
  const appPath = params.argv.length >= 2 ? path.resolve(params.argv[1]) : null;
  if (appPath) {
    params.app.setAsDefaultProtocolClient(params.protocol, params.execPath, [appPath]);
  } else {
    params.app.setAsDefaultProtocolClient(params.protocol);
  }
}

export function installDesktopApplicationLifecycle(params: {
  app: App;
  protocol: string;
  argv: string[];
  execPath: string;
  platform: NodeJS.Platform;
  isDefaultApp: boolean;
  initializeTray: () => void;
  initializeUpdater: () => void;
  rebuildAppMenu: () => void;
  registerIpc: () => void;
  createMainWindow: () => void;
  initializeGlobalShortcut: () => void;
  handleStartupArgs: (argv: string[]) => void;
  startBackgroundRuntime: () => void;
  activate: () => void;
  shutdown: () => Promise<void>;
  showMainWindowCreateError: (error: unknown) => void;
  showStartupError: (error: unknown) => void;
  logger: LoggerLike | null;
}): void {
  (params.app as AppWithQuitFlag).isQuitting = false;
  let shutdownComplete = false;
  let shutdownStarted = false;
  params.app.on('before-quit', (event) => {
    if (shutdownComplete) return;
    event.preventDefault();
    if (shutdownStarted) return;
    shutdownStarted = true;
    (params.app as AppWithQuitFlag).isQuitting = true;
    void params.shutdown().then(
      () => {
        shutdownComplete = true;
        params.app.quit();
      },
      (error) => {
        shutdownStarted = false;
        params.logger?.error?.('APP_SHUTDOWN_ERR', { error });
      }
    );
  });

  void params.app.whenReady().then(() => {
    let startupStage = 'start';
    try {
      startupStage = 'tray-initialization';
      params.initializeTray();
      try {
        params.initializeUpdater();
      } catch (error) {
        params.logger?.error?.('AUTO_UPDATE_INIT_ERR', { err: error });
      }
      try {
        params.rebuildAppMenu();
      } catch {
        // UI menu construction is non-critical during startup.
      }

      startupStage = 'protocol-registration';
      try {
        registerProtocol(params);
      } catch (error) {
        params.logger?.warn?.('SET_DEFAULT_PROTOCOL_CLIENT_ERR', { err: error });
      }

      startupStage = 'ipc-registration';
      params.registerIpc();

      startupStage = 'main-window-create';
      try {
        params.createMainWindow();
      } catch (error) {
        params.logger?.error?.('MAIN_WINDOW_CREATE_ERR', { err: error });
        try {
          params.showMainWindowCreateError(error);
        } catch (dialogError) {
          params.logger?.error?.('MAIN_WINDOW_CREATE_DIALOG_ERR', { err: dialogError });
        }
      }

      try {
        params.initializeGlobalShortcut();
      } catch (error) {
        params.logger?.error?.('GLOBAL_SHORTCUT_INIT_ERR', { err: error });
      }

      startupStage = 'deep-link-startup-args';
      params.handleStartupArgs(params.argv);
      params.startBackgroundRuntime();
    } catch (error) {
      params.logger?.error?.('APP_STARTUP_ERR', {
        stage: startupStage,
        err: error,
        stack: error instanceof Error ? error.stack : null,
      });
      try {
        params.showStartupError(error);
      } catch (dialogError) {
        params.logger?.error?.('APP_STARTUP_DIALOG_ERR', { err: dialogError });
      }
    }
  });

  params.app.on('activate', params.activate);
  params.app.on('window-all-closed', () => {
    if (params.platform !== 'darwin') params.app.quit();
  });
}
