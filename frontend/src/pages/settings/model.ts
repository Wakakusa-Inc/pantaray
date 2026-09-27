import type {
  CaptureAppEntry,
  CaptureFilter,
  ElectronCaptureSettings,
  IdeFileRules,
  IdeSensitivePresets,
  InstalledApp,
} from './types';

export const DEFAULT_IDE_SENSITIVE_PRESETS: IdeSensitivePresets = {
  blockEnvFiles: true,
};

export function getIdeSensitivePresets(
  rules: IdeFileRules | null | undefined
): IdeSensitivePresets {
  const blockEnvFiles = rules?.sensitivePresets?.blockEnvFiles;
  return {
    blockEnvFiles:
      typeof blockEnvFiles === 'boolean'
        ? blockEnvFiles
        : DEFAULT_IDE_SENSITIVE_PRESETS.blockEnvFiles,
  };
}

export function normalizeIdeFileRulesForUi(rules: IdeFileRules): IdeFileRules {
  return {
    mode: rules.mode === 'off' ? 'off' : 'on',
    onFileNameUnavailable: rules.onFileNameUnavailable === 'block' ? 'block' : 'allow',
    sensitivePresets: getIdeSensitivePresets(rules),
  };
}

/**
 * Identity of a filter entry: the same value the recorder compares a running app
 * against, so two entries that would match the same app cannot both be listed.
 */
export function captureAppKey(entry: CaptureAppEntry): string {
  return (entry.bundleId ?? entry.name).toLowerCase();
}

export const DEFAULT_CAPTURE_FILTER: CaptureFilter = {
  apps: { mode: 'exclude', entries: [] },
  websites: { mode: 'exclude', hosts: [] },
};

function normalizeMode(value: unknown) {
  return value === 'include_only' ? ('include_only' as const) : ('exclude' as const);
}

export function normalizeCaptureFilterForUi(settings: unknown): CaptureFilter {
  const raw = (settings ?? {}) as {
    apps?: { mode?: unknown; entries?: unknown };
    websites?: { mode?: unknown; hosts?: unknown };
  };
  const rawEntries = Array.isArray(raw.apps?.entries) ? raw.apps.entries : [];
  const entries: CaptureAppEntry[] = [];
  const seen = new Set<string>();
  for (const candidate of rawEntries) {
    if (!candidate || typeof candidate !== 'object') continue;
    const { name, bundleId } = candidate as { name?: unknown; bundleId?: unknown };
    const entry: CaptureAppEntry = {
      name: String(name ?? '').trim(),
      bundleId: typeof bundleId === 'string' && bundleId.trim() ? bundleId.trim() : null,
    };
    if (!entry.name && !entry.bundleId) continue;
    if (!entry.name) entry.name = entry.bundleId as string;
    if (seen.has(captureAppKey(entry))) continue;
    seen.add(captureAppKey(entry));
    entries.push(entry);
  }
  const rawHosts = Array.isArray(raw.websites?.hosts) ? raw.websites.hosts : [];
  const hosts = [
    ...new Set(
      rawHosts
        .map((host) =>
          String(host ?? '')
            .trim()
            .toLowerCase()
        )
        .filter(Boolean)
    ),
  ];
  return {
    apps: { mode: normalizeMode(raw.apps?.mode), entries },
    websites: { mode: normalizeMode(raw.websites?.mode), hosts },
  };
}

export function buildCaptureSettingsPayload(filter: CaptureFilter): ElectronCaptureSettings {
  return {
    version: 2,
    apps: { mode: filter.apps.mode, entries: filter.apps.entries },
    websites: { mode: filter.websites.mode, hosts: filter.websites.hosts },
  };
}

export type WebsiteHostParseResult =
  | { ok: true; host: string }
  | { ok: false; error: 'invalid_host' };

/**
 * A DNS name the recorder can match: at least two labels of letters, digits and inner
 * hyphens. Anything else (`*.example.com`, `foo..bar`, `exa_mple.com`) is rejected at
 * the input rather than stored: such a host matches no real hostname, so an exclusion
 * the user believes is in place would keep recording the site, and the recorder can
 * reject the whole generated configuration over it.
 */
const DNS_HOST_PATTERN = /^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$/;

/**
 * Accepts a bare domain or a pasted URL and returns the canonical `URL.hostname`
 * form the recorder compares against (lowercase, IDNA-encoded, no port or path).
 */
export function parseWebsiteHost(rawInput: string): WebsiteHostParseResult {
  const trimmed = rawInput.trim();
  if (!trimmed) return { ok: false, error: 'invalid_host' };
  let parsed: URL;
  try {
    parsed = new URL(trimmed.includes('://') ? trimmed : `https://${trimmed}`);
  } catch {
    return { ok: false, error: 'invalid_host' };
  }
  const host = parsed.hostname.toLowerCase();
  if (!DNS_HOST_PATTERN.test(host)) return { ok: false, error: 'invalid_host' };
  return { ok: true, host };
}

/** Installed apps matching a picker query, with already-listed apps removed. */
export function filterInstalledApps(
  apps: readonly InstalledApp[],
  query: string,
  listed: readonly CaptureAppEntry[]
): InstalledApp[] {
  const needle = query.trim().toLowerCase();
  const listedKeys = new Set(listed.map(captureAppKey));
  return apps.filter(
    (app) =>
      !listedKeys.has(captureAppKey(app)) &&
      (!needle ||
        app.name.toLowerCase().includes(needle) ||
        (app.bundleId ?? '').toLowerCase().includes(needle))
  );
}

/**
 * Installed app a filter entry names, used to show the entry's real bundle icon.
 *
 * An entry keeps only what the recorder matches on, so it is looked up the same way
 * the recorder resolves it: by bundle identifier when it has one, and by display name
 * for a legacy entry that was migrated without one. Those entries are keyed by name
 * while installed apps are keyed by bundle id, so `captureAppKey` — the identity used
 * to keep the list free of duplicates — cannot pair them up.
 */
export function findInstalledApp(
  apps: readonly InstalledApp[],
  entry: CaptureAppEntry
): InstalledApp | undefined {
  const bundleId = entry.bundleId?.toLowerCase();
  if (bundleId) return apps.find((app) => app.bundleId?.toLowerCase() === bundleId);
  const name = entry.name.trim().toLowerCase();
  return apps.find((app) => app.name.trim().toLowerCase() === name);
}
