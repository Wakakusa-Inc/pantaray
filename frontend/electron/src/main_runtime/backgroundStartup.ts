type LoggerLike = {
  error?: (name: string, payload?: unknown) => void;
};

function logFailure(logger: LoggerLike | null, event: string, error: unknown): void {
  logger?.error?.(event, { err: error });
}

async function startLocalBackendHelper(params: {
  ensureStarted: () => Promise<unknown>;
  logger: LoggerLike | null;
}): Promise<void> {
  try {
    await params.ensureStarted();
  } catch (error) {
    logFailure(params.logger, 'LOCAL_BACKEND_HELPER_START_ERR', error);
  }
}

export async function startDesktopBackgroundRuntime(params: {
  installLocalBackendConfig: () => void;
  ensureLocalBackendStarted: () => Promise<unknown>;
  initializeAuth: () => Promise<unknown>;
  applyPendingAuthCallback: () => void;
  ensureOrchestrationConnected: () => void;
  reportRuntimeConfigFailure: (error: unknown) => void;
  logger: LoggerLike | null;
}): Promise<void> {
  let helperStartup: Promise<void>;
  try {
    params.installLocalBackendConfig();
    helperStartup = startLocalBackendHelper({
      ensureStarted: params.ensureLocalBackendStarted,
      logger: params.logger,
    });
  } catch (error) {
    logFailure(params.logger, 'LOCAL_BACKEND_RUNTIME_CONFIG_ERR', error);
    params.reportRuntimeConfigFailure(error);
    return;
  }

  try {
    await params.initializeAuth();
  } catch (error) {
    logFailure(params.logger, 'SUPABASE_WIRING_INIT_ERR', error);
  } finally {
    try {
      params.applyPendingAuthCallback();
    } catch (error) {
      logFailure(params.logger, 'PENDING_AUTH_CALLBACK_APPLY_ERR', error);
    }
  }

  await helperStartup;

  try {
    params.ensureOrchestrationConnected();
  } catch (error) {
    logFailure(params.logger, 'ORCHESTRATION_CONNECT_ERR', error);
  }
}
