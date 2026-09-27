/**
 * Capture privacy settings — the recording filter the user edits.
 *
 * Two axes, each with the same two modes:
 * - apps: record every app except the listed ones (`exclude`), or only the listed ones
 *   (`include_only`).
 * - websites: the same choice for browser URLs.
 *
 * The recorder identifies an app by `bundle_id` when it has one and only falls back to
 * the display name, so an entry keeps both and `captureAppKey` picks the one the
 * recorder will compare against.
 *
 * Settings are stored per signed-in user under the scoped settings directory. Renderer
 * input is never trusted: it is validated at the IPC boundary and normalized again here.
 */

import fs from 'fs';

import { resolveScopedSettingsPath, SCOPED_PREFERENCE_FILES } from '../settings/scope';

export type CaptureFilterMode = 'exclude' | 'include_only';

export type CaptureAppEntry = {
  /** Display name shown in the settings UI. */
  name: string;
  /** Bundle identifier; null only for an app whose bundle could not be read. */
  bundleId: string | null;
};

export type CaptureAppFilter = {
  mode: CaptureFilterMode;
  entries: CaptureAppEntry[];
};

export type CaptureWebsiteFilter = {
  mode: CaptureFilterMode;
  /** Canonical `URL.hostname` values (lowercase, IDNA-encoded, no port). */
  hosts: string[];
};

export type IdeFileRules = {
  /** Derived from the presets below; kept because the recorder policy reads it. */
  mode: 'off' | 'on';
  onFileNameUnavailable: 'block' | 'allow';
  sensitivePresets: { blockEnvFiles: boolean };
};

export const CAPTURE_PRIVACY_SETTINGS_VERSION = 2;

export type CapturePrivacySettings = {
  version: typeof CAPTURE_PRIVACY_SETTINGS_VERSION;
  apps: CaptureAppFilter;
  websites: CaptureWebsiteFilter;
  ideFileRules: IdeFileRules;
};

export type CapturePrivacyManager = {
  /** Switches the settings scope (user_id), reloading that scope's settings. */
  setSettingsScope: (userId: string | null) => CapturePrivacySettings;
  getCaptureSettings: () => CapturePrivacySettings;
  /** Normalizes and stores renderer-provided settings. */
  updateCaptureSettings: (next: unknown) => CapturePrivacySettings;
  getIdeFileRules: () => IdeFileRules;
  updateIdeFileRules: (nextRules: unknown) => IdeFileRules;
};

/** The value the recorder compares a running app against. */
export function captureAppKey(entry: CaptureAppEntry): string {
  return entry.bundleId ?? entry.name;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object';
}

function safeParseJson(rawText: string): unknown {
  try {
    return JSON.parse(rawText);
  } catch {
    return null;
  }
}

function normalizeFilterMode(value: unknown): CaptureFilterMode {
  return value === 'include_only' ? 'include_only' : 'exclude';
}

function normalizeAppEntries(value: unknown): CaptureAppEntry[] {
  if (!Array.isArray(value)) return [];
  const entries: CaptureAppEntry[] = [];
  const seen = new Set<string>();
  for (const raw of value) {
    if (!isRecord(raw)) continue;
    const name = String(raw.name ?? '').trim();
    const bundleId = String(raw.bundleId ?? '').trim() || null;
    if (!name && !bundleId) continue;
    const entry: CaptureAppEntry = { name: name || (bundleId as string), bundleId };
    const key = captureAppKey(entry).toLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    entries.push(entry);
  }
  return entries;
}

function normalizeHosts(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  const hosts: string[] = [];
  const seen = new Set<string>();
  for (const raw of value) {
    const host = String(raw ?? '')
      .trim()
      .toLowerCase();
    if (!host || seen.has(host)) continue;
    seen.add(host);
    hosts.push(host);
  }
  return hosts;
}

export function normalizeIdeFileRules(value: unknown): IdeFileRules {
  const rules = isRecord(value) ? value : {};
  const presets = isRecord(rules.sensitivePresets) ? rules.sensitivePresets : {};
  const blockEnvFiles = presets.blockEnvFiles !== false;
  return {
    // The UI exposes the preset only; `mode` stays derived so both cannot disagree.
    mode: blockEnvFiles ? 'on' : 'off',
    onFileNameUnavailable: rules.onFileNameUnavailable === 'block' ? 'block' : 'allow',
    sensitivePresets: { blockEnvFiles },
  };
}

export function defaultCapturePrivacySettings(): CapturePrivacySettings {
  return {
    version: CAPTURE_PRIVACY_SETTINGS_VERSION,
    apps: { mode: 'exclude', entries: [] },
    websites: { mode: 'exclude', hosts: [] },
    ideFileRules: normalizeIdeFileRules(null),
  };
}

/**
 * Fallback for settings that exist but cannot be read.
 *
 * Whether recording is on is stored in a different file, so the recorder can resume
 * while this one is unreadable. The `exclude`-with-empty-list default would then record
 * everything the unreadable policy may have forbidden, so an unreadable file records
 * nothing until the user saves a filter again.
 */
function failClosedCapturePrivacySettings(): CapturePrivacySettings {
  return {
    version: CAPTURE_PRIVACY_SETTINGS_VERSION,
    apps: { mode: 'include_only', entries: [] },
    websites: { mode: 'include_only', hosts: [] },
    ideFileRules: normalizeIdeFileRules(null),
  };
}

export function normalizeCapturePrivacySettings(value: unknown): CapturePrivacySettings {
  const settings = isRecord(value) ? value : {};
  const apps = isRecord(settings.apps) ? settings.apps : {};
  const websites = isRecord(settings.websites) ? settings.websites : {};
  return {
    version: CAPTURE_PRIVACY_SETTINGS_VERSION,
    apps: { mode: normalizeFilterMode(apps.mode), entries: normalizeAppEntries(apps.entries) },
    websites: {
      mode: normalizeFilterMode(websites.mode),
      hosts: normalizeHosts(websites.hosts),
    },
    ideFileRules: normalizeIdeFileRules(settings.ideFileRules),
  };
}

function legacyRuleHosts(value: unknown): string[] {
  return normalizeHosts(
    (Array.isArray(value) ? value : []).map((rule) => (isRecord(rule) ? rule.host : null))
  );
}

/**
 * A legacy rule the host-wide filter can represent: the whole host, subdomains
 * included. A rule limited to a path prefix, or to the bare host without its
 * subdomains, covered less than the migrated host would. The legacy rule editor
 * stored a bare domain as `pathPrefix: '/'` (`new URL(...).pathname`), which is
 * the same as no path limit.
 */
function isHostWideRule(rule: unknown): boolean {
  if (!isRecord(rule)) return false;
  const pathPrefix = typeof rule.pathPrefix === 'string' ? rule.pathPrefix : '';
  return (pathPrefix === '' || pathPrefix === '/') && rule.matchSubdomains !== false;
}

/**
 * Maps the legacy browser URL rules onto the two-mode website filter.
 *
 * The recorder denies a `blockList` match before it consults the mode, so the block
 * list is live data in every mode but `off`. The new filter is host-wide, so a legacy
 * rule that covered only a path prefix or only the bare host cannot be migrated as a
 * host-wide allow entry — that would record more than the legacy rules did. Migration
 * therefore only ever narrows:
 * - `off` recorded no browser URL at all, so the only faithful mapping is only mode
 *   with an empty list.
 * - `rules` + `block_by_default` recorded only the allow list — only mode with the
 *   allow entries that already covered a whole host, minus the blocked ones.
 * - `rules` + `allow_by_default` recorded every site except the block list — except
 *   mode with those hosts.
 * - `all_sites` recorded every site except the block list — except mode, same hosts.
 */
function migrateLegacyBrowserUrlRules(legacyRules: unknown): CaptureWebsiteFilter {
  const rules = isRecord(legacyRules) ? legacyRules : {};
  if (rules.mode === 'off') return { mode: 'include_only', hosts: [] };
  const blockedHosts = legacyRuleHosts(rules.blockList);
  if (rules.mode !== 'rules' || rules.defaultPolicy !== 'block_by_default') {
    return { mode: 'exclude', hosts: blockedHosts };
  }
  const blocked = new Set(blockedHosts);
  const allowedHosts = legacyRuleHosts(
    (Array.isArray(rules.allowList) ? rules.allowList : []).filter(isHostWideRule)
  );
  return { mode: 'include_only', hosts: allowedHosts.filter((host) => !blocked.has(host)) };
}

/**
 * Upgrades settings written before the two-mode filter.
 *
 * The legacy shape was an app allow list (`apps[].mode === 'all'`) plus browser URL
 * rules, so an existing allow list becomes only mode with the same apps and an empty
 * one becomes except mode. Legacy entries carry display names only; `resolveBundleId`
 * upgrades them, because a name-only entry would not match an app that has a bundle id.
 */
export function migrateLegacyCapturePrivacySettings(
  legacy: unknown,
  resolveBundleId: (name: string) => string | null
): CapturePrivacySettings {
  const settings = isRecord(legacy) ? legacy : {};
  const legacyApps = Array.isArray(settings.apps) ? settings.apps : [];
  const entries: CaptureAppEntry[] = [];
  const seen = new Set<string>();
  for (const raw of legacyApps) {
    if (!isRecord(raw)) continue;
    const name = String(raw.name ?? '').trim();
    if (!name) continue;
    // The legacy normalizer mapped `workspaces` to `all` before consulting the
    // deprecated `enabled` flag, so such an app was being recorded.
    const enabled =
      raw.mode === 'off'
        ? false
        : raw.mode === 'all' || raw.mode === 'workspaces' || raw.enabled !== false;
    if (!enabled) continue;
    const entry: CaptureAppEntry = { name, bundleId: resolveBundleId(name) };
    const key = captureAppKey(entry).toLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    entries.push(entry);
  }

  return {
    version: CAPTURE_PRIVACY_SETTINGS_VERSION,
    apps: { mode: entries.length > 0 ? 'include_only' : 'exclude', entries },
    websites: migrateLegacyBrowserUrlRules(settings.browserUrlRules),
    ideFileRules: normalizeIdeFileRules(settings.ideFileRules),
  };
}

export function createCapturePrivacyManager(params: {
  userDataDir: string;
  initialUserId?: string | null;
  /** Injected so the migration can upgrade display names to bundle identifiers. */
  resolveAppBundleId: (name: string) => string | null;
}): CapturePrivacyManager {
  const userDataDir = String(params.userDataDir || '').trim();
  let currentSettingsScopeUserId: string | null = params.initialUserId ?? null;
  let settingsPath = resolveScopedSettingsPath({
    userDataDir,
    userId: currentSettingsScopeUserId,
    fileName: SCOPED_PREFERENCE_FILES.capturePrivacy,
  });

  function loadCapturePrivacySettings(pathToLoad: string): CapturePrivacySettings {
    try {
      if (!fs.existsSync(pathToLoad)) return defaultCapturePrivacySettings();
      const stored = safeParseJson(fs.readFileSync(pathToLoad, 'utf8'));
      // Content that is not a settings object says nothing about the stored policy.
      if (!isRecord(stored)) return failClosedCapturePrivacySettings();
      if (stored.version === CAPTURE_PRIVACY_SETTINGS_VERSION) {
        return normalizeCapturePrivacySettings(stored);
      }
      const migrated = migrateLegacyCapturePrivacySettings(stored, params.resolveAppBundleId);
      saveCapturePrivacySettings(migrated, pathToLoad);
      return migrated;
    } catch (error) {
      console.error('Failed to load capture privacy settings:', error);
      return failClosedCapturePrivacySettings();
    }
  }

  function saveCapturePrivacySettings(
    settings: CapturePrivacySettings,
    pathToSave: string = settingsPath
  ): void {
    fs.writeFileSync(pathToSave, JSON.stringify(settings, null, 2));
  }

  let capturePrivacySettings: CapturePrivacySettings = loadCapturePrivacySettings(settingsPath);

  return {
    setSettingsScope: (userId: string | null) => {
      currentSettingsScopeUserId = userId;
      settingsPath = resolveScopedSettingsPath({
        userDataDir,
        userId: currentSettingsScopeUserId,
        fileName: SCOPED_PREFERENCE_FILES.capturePrivacy,
      });
      capturePrivacySettings = loadCapturePrivacySettings(settingsPath);
      return capturePrivacySettings;
    },
    getCaptureSettings: () => capturePrivacySettings,
    updateCaptureSettings: (next: unknown) => {
      // The filter dialog saves apps and websites only; IDE rules keep their stored
      // value so a concurrent IDE-rule change is not clobbered by a stale payload.
      const patch = isRecord(next) ? next : {};
      const nextSettings = normalizeCapturePrivacySettings({
        ...patch,
        ideFileRules: patch.ideFileRules ?? capturePrivacySettings.ideFileRules,
      });
      saveCapturePrivacySettings(nextSettings);
      capturePrivacySettings = nextSettings;
      return capturePrivacySettings;
    },
    getIdeFileRules: () => capturePrivacySettings.ideFileRules,
    updateIdeFileRules: (nextRules: unknown) => {
      const nextSettings: CapturePrivacySettings = {
        ...capturePrivacySettings,
        ideFileRules: normalizeIdeFileRules(nextRules),
      };
      saveCapturePrivacySettings(nextSettings);
      capturePrivacySettings = nextSettings;
      return capturePrivacySettings.ideFileRules;
    },
  };
}
