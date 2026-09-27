import type { App, Dialog } from 'electron';
import fs from 'fs';
import path from 'path';
import { createRequire } from 'module';

import dotenv from 'dotenv';

import { defaultUiLanguage } from '../ui/uiLanguage';
import { getStartupDialogCopy } from '../ui/mainProcessCopy';

export type DesktopRuntimeConfig = {
  web_app_origin: string;
  supabase_url: string;
  supabase_publishable_key: string;
  backend_url: string;
  api_host_origin: string;
};

type LocalBackendRuntimeConfig = {
  LOCAL_DB_PATH?: unknown;
  LOCAL_APP_RUNTIME_MANIFEST_PATH?: unknown;
  LOCAL_RUNTIME_CONTROL_SOCKET_PATH?: unknown;
  LOCAL_BACKEND_HELPER_EXECUTABLE?: unknown;
};

type LoggerLike = {
  info?: (name: string, payload?: unknown) => void;
  error?: (name: string, payload?: unknown) => void;
  safeUrlSummary?: (url: string) => unknown;
};

type MaterializedRuntime = {
  bundlePath?: string;
  sourceEnvPath?: string;
  configPath: string;
  config: LocalBackendRuntimeConfig;
};

type LocalBackendRuntimeModule = {
  materializeLocalBackendRuntimeConfig: (params: {
    resourcesPath: string;
    userDataDir: string;
    logsDir: string;
  }) => MaterializedRuntime;
  materializeDevelopmentLocalBackendRuntimeConfig: (params: {
    agentsRoot: string;
    userDataDir: string;
    logsDir: string;
  }) => MaterializedRuntime;
  resolveLoopbackBinding: (backendUrl: string) => {
    appPort: number;
    bindHost: string;
    bindPort: number;
  };
};

export type DesktopRuntime = {
  config: DesktopRuntimeConfig | null;
  getBackendUrl: () => string | null;
  getAppRuntimeManifestPath: () => string;
  setBackendUrl: (nextUrl: string) => void;
  installLocalBackendConfig: () => void;
  getLocalBackendControlSocketPath: () => string;
  getLocalBackendHelperExecutablePath: () => string | null;
  getLoopbackBinding: () => { appPort: number; bindHost: string; bindPort: number };
};

const loadNodeModule = createRequire(__filename);

function summarizeUrl(logger: LoggerLike | null, url: string): unknown {
  return logger?.safeUrlSummary ? logger.safeUrlSummary(url) : url;
}

export function loadDevelopmentEnvironment(params: {
  frontendRoot: string;
  isDevelopment: boolean;
}): void {
  if (!params.isDevelopment) return;
  for (const filename of ['.env.local', '.env']) {
    const envPath = path.resolve(params.frontendRoot, filename);
    if (!fs.existsSync(envPath)) continue;
    dotenv.config({ path: envPath });
    return;
  }
}

function loadConfig(params: {
  app: App;
  dialog: Dialog;
  logger: LoggerLike | null;
}): DesktopRuntimeConfig | null {
  const { loadRuntimeConfig } = loadNodeModule('../../runtime_config') as {
    loadRuntimeConfig: (input: { isPackaged: boolean }) => DesktopRuntimeConfig;
  };
  try {
    const config = loadRuntimeConfig({ isPackaged: params.app.isPackaged });
    params.logger?.info?.('RUNTIME_CONFIG_LOADED', {
      ok: true,
      is_packaged: Boolean(params.app.isPackaged),
      web_app_origin: summarizeUrl(params.logger, config.web_app_origin),
      supabase_url: summarizeUrl(params.logger, config.supabase_url),
      backend_url: summarizeUrl(params.logger, config.backend_url),
    });
    return config;
  } catch (error) {
    params.logger?.error?.('RUNTIME_CONFIG_ERR', { ok: false, err: error });
    if (!params.app.isPackaged) return null;
    const message = error instanceof Error ? error.message : String(error);
    const copy = getStartupDialogCopy(defaultUiLanguage(params.app.getLocale()));
    try {
      params.dialog.showErrorBox(copy.runtimeConfigTitle, copy.runtimeConfigBody(message));
    } catch (dialogError) {
      params.logger?.error?.('RUNTIME_CONFIG_DIALOG_ERR', { err: dialogError });
    }
    try {
      params.app.quit();
    } catch (quitError) {
      params.logger?.error?.('RUNTIME_CONFIG_QUIT_ERR', { err: quitError });
    }
    return null;
  }
}

export function createDesktopRuntime(params: {
  app: App;
  dialog: Dialog;
  frontendRoot: string;
  logger: LoggerLike | null;
}): DesktopRuntime {
  const runtimeModule = loadNodeModule(
    '../../local_backend_runtime_config'
  ) as LocalBackendRuntimeModule;
  const config = loadConfig(params);
  let backendUrl = config ? String(config.backend_url).trim() : null;
  let localBackendConfig: LocalBackendRuntimeConfig | null = null;

  function installLocalBackendConfig(): void {
    if (!config) throw new Error('Missing runtime config for local backend startup.');
    const shared = {
      userDataDir: params.app.getPath('userData'),
      logsDir: params.app.getPath('logs'),
    };
    const materialized = params.app.isPackaged
      ? runtimeModule.materializeLocalBackendRuntimeConfig({
          ...shared,
          resourcesPath: process.resourcesPath,
        })
      : runtimeModule.materializeDevelopmentLocalBackendRuntimeConfig({
          ...shared,
          agentsRoot: path.resolve(params.frontendRoot, '..', 'agents'),
        });
    localBackendConfig = materialized.config;
    process.env.PANTARAY_AGENTS_RUNTIME_CONFIG_PATH = materialized.configPath;
    params.logger?.info?.('LOCAL_BACKEND_RUNTIME_CONFIG_READY', {
      ok: true,
      config_path: materialized.configPath,
      ...(materialized.bundlePath ? { bundle_path: materialized.bundlePath } : {}),
      ...(materialized.sourceEnvPath ? { source_env_path: materialized.sourceEnvPath } : {}),
    });
  }

  function getRequiredLocalString(key: keyof LocalBackendRuntimeConfig): string {
    const value = localBackendConfig?.[key];
    if (typeof value === 'string' && value.trim()) return value.trim();
    throw new Error(`Missing materialized local backend value: ${key}.`);
  }

  return {
    config,
    getBackendUrl: () => backendUrl,
    setBackendUrl: (nextUrl) => {
      const normalized = String(nextUrl).trim();
      if (!normalized) throw new Error('runtime backend URL must not be empty.');
      if (backendUrl === normalized) return;
      backendUrl = normalized;
      params.logger?.info?.('LOCAL_BACKEND_RUNTIME_URL_UPDATED', {
        backend_url: summarizeUrl(params.logger, normalized),
      });
    },
    installLocalBackendConfig,
    getAppRuntimeManifestPath: () => getRequiredLocalString('LOCAL_APP_RUNTIME_MANIFEST_PATH'),
    getLocalBackendControlSocketPath: () =>
      getRequiredLocalString('LOCAL_RUNTIME_CONTROL_SOCKET_PATH'),
    getLocalBackendHelperExecutablePath: () => {
      const value = localBackendConfig?.LOCAL_BACKEND_HELPER_EXECUTABLE;
      return typeof value === 'string' && value.trim() ? value.trim() : null;
    },
    getLoopbackBinding: () => {
      if (!config) throw new Error('Missing runtime config for local backend helper binding.');
      return runtimeModule.resolveLoopbackBinding(config.backend_url);
    },
  };
}
