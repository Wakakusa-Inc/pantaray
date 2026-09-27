import { randomUUID } from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';

import type {
  GlobalShortcutChangeResult,
  GlobalShortcutFailure,
  GlobalShortcutState,
} from '../ipc/schemas/shortcut';

const SETTINGS_VERSION = 1;
const SETTINGS_FILE_NAME = 'global-shortcut.json';

export class GlobalShortcutSettingsError extends Error {}
export class GlobalShortcutRegistrationError extends Error {}

export type GlobalShortcutStore = {
  load: () => string | null;
  save: (accelerator: string) => void;
};

type GlobalShortcutRegistry = {
  register: (accelerator: string, callback: () => void) => boolean;
  unregister: (accelerator: string) => void;
  unregisterAll: () => void;
};

function requireAccelerator(value: unknown): string {
  if (typeof value !== 'string' || !value.trim()) {
    throw new GlobalShortcutSettingsError(
      'Global shortcut accelerator must be a non-empty string.'
    );
  }
  return value.trim();
}

function parseSettings(raw: string): string {
  let value: unknown;
  try {
    value = JSON.parse(raw);
  } catch {
    throw new GlobalShortcutSettingsError('Global shortcut settings are malformed.');
  }
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    throw new GlobalShortcutSettingsError('Global shortcut settings are malformed.');
  }
  const settings = value as { version?: unknown; accelerator?: unknown };
  if (settings.version !== SETTINGS_VERSION) {
    throw new GlobalShortcutSettingsError('Global shortcut settings version is unsupported.');
  }
  return requireAccelerator(settings.accelerator);
}

export function createGlobalShortcutStore(userDataDir: string): GlobalShortcutStore {
  const settingsPath = path.join(userDataDir, SETTINGS_FILE_NAME);
  return {
    load: () =>
      fs.existsSync(settingsPath) ? parseSettings(fs.readFileSync(settingsPath, 'utf8')) : null,
    save: (accelerator) => {
      const normalized = requireAccelerator(accelerator);
      fs.mkdirSync(path.dirname(settingsPath), { recursive: true });
      const temporaryPath = `${settingsPath}.tmp-${randomUUID()}`;
      try {
        fs.writeFileSync(
          temporaryPath,
          `${JSON.stringify({ version: SETTINGS_VERSION, accelerator: normalized })}\n`,
          { encoding: 'utf8', flag: 'wx', mode: 0o600 }
        );
        fs.renameSync(temporaryPath, settingsPath);
      } finally {
        if (fs.existsSync(temporaryPath)) fs.unlinkSync(temporaryPath);
      }
    },
  };
}

export function createGlobalShortcutController(params: {
  registry: GlobalShortcutRegistry;
  store: GlobalShortcutStore;
  initialAccelerator: string | null;
  onShortcut: () => void;
}) {
  let activeAccelerator: string | null = null;
  let configuredAccelerator: string | null = null;
  let failure: GlobalShortcutFailure | null = null;
  const initialAccelerator = params.initialAccelerator
    ? requireAccelerator(params.initialAccelerator)
    : null;

  const register = (accelerator: string): void => {
    let registered = false;
    try {
      registered = params.registry.register(accelerator, params.onShortcut);
    } catch {
      throw new GlobalShortcutRegistrationError(
        `Global shortcut registration failed: ${accelerator}`
      );
    }
    if (!registered) {
      throw new GlobalShortcutRegistrationError(
        `Global shortcut registration failed: ${accelerator}`
      );
    }
  };
  const getState = (): GlobalShortcutState => ({
    accelerator: configuredAccelerator,
    failure,
  });
  const replaceShortcut = (nextAccelerator: string): GlobalShortcutState => {
    const next = requireAccelerator(nextAccelerator);
    if (next === activeAccelerator) return getState();
    register(next);
    try {
      params.store.save(next);
    } catch (error) {
      params.registry.unregister(next);
      throw error;
    }
    const previous = activeAccelerator;
    activeAccelerator = next;
    configuredAccelerator = next;
    failure = null;
    if (previous) params.registry.unregister(previous);
    return getState();
  };
  const changeShortcut = (nextAccelerator: string): GlobalShortcutChangeResult => {
    try {
      return { ok: true, state: replaceShortcut(nextAccelerator) };
    } catch (error) {
      return {
        ok: false,
        reason:
          error instanceof GlobalShortcutRegistrationError
            ? 'registration_unavailable'
            : 'persistence_failed',
        state: getState(),
      };
    }
  };
  const initialize = (): void => {
    params.registry.unregisterAll();
    activeAccelerator = null;
    configuredAccelerator = null;
    failure = null;
    let storedAccelerator: string | null;
    try {
      storedAccelerator = params.store.load();
    } catch (error) {
      failure = 'settings_unreadable';
      throw error;
    }
    if (storedAccelerator) {
      configuredAccelerator = storedAccelerator;
      try {
        register(storedAccelerator);
      } catch (error) {
        failure = 'registration_unavailable';
        throw error;
      }
      activeAccelerator = storedAccelerator;
      return;
    }
    if (!initialAccelerator) return;
    configuredAccelerator = initialAccelerator;
    try {
      replaceShortcut(initialAccelerator);
    } catch (error) {
      failure =
        error instanceof GlobalShortcutRegistrationError
          ? 'registration_unavailable'
          : 'persistence_failed';
      throw error;
    }
  };

  return { changeShortcut, getState, initialize };
}
