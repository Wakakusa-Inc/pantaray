/**
 * Installed macOS application index.
 *
 * The recorder matches an app by `bundle_id` when the running app has one and only
 * falls back to the display name (see the Zanei privacy matcher). A filter entry that
 * carries only a display name therefore never matches a normal GUI app, so the picker
 * and the legacy-settings migration both need real bundle identifiers.
 *
 * Bundle identifiers come from Spotlight in one `mdls` call for the whole list; any
 * bundle Spotlight does not answer for — or answers for without the identifier — is
 * read directly from its `Info.plist`, so an unindexed volume degrades in speed rather
 * than silently losing the identifier.
 */

import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

export type InstalledApp = {
  /** Localized display name, or the bundle name when Spotlight has no display name. */
  name: string;
  bundleId: string | null;
  path: string;
};

const APPLICATION_DIRECTORIES = ['/Applications', '/System/Applications'];

/**
 * Levels scanned under each root. Vendors install into a subfolder
 * (`/Applications/Adobe Photoshop 2026/Adobe Photoshop.app`) and `Utilities` is one
 * level down as well, so two levels cover every real installation layout. Bundles are
 * never descended into: their own `Contents` holds helper `.app`s the user never picks.
 */
const APPLICATION_SCAN_DEPTH = 2;

/** Spotlight reports firmlinked system paths; both spellings name the same bundle. */
const DATA_VOLUME_PREFIX = '/System/Volumes/Data';

const MDLS_ATTRIBUTES = ['kMDItemPath', 'kMDItemCFBundleIdentifier', 'kMDItemDisplayName'] as const;

function collectApplicationBundles(directory: string, depth: number, bundles: string[]): void {
  let entries: fs.Dirent[];
  try {
    entries = fs.readdirSync(directory, { withFileTypes: true });
  } catch {
    return;
  }
  for (const entry of entries) {
    const entryPath = path.join(directory, entry.name);
    if (entry.name.endsWith('.app')) {
      bundles.push(entryPath);
    } else if (depth > 1 && entry.isDirectory()) {
      collectApplicationBundles(entryPath, depth - 1, bundles);
    }
  }
}

function applicationBundlePaths(): string[] {
  const directories = [...APPLICATION_DIRECTORIES, path.join(os.homedir(), 'Applications')];
  const bundles: string[] = [];
  for (const directory of directories) {
    collectApplicationBundles(directory, APPLICATION_SCAN_DEPTH, bundles);
  }
  return bundles.sort((left, right) => left.localeCompare(right));
}

function parseMdlsValue(raw: string): string | null {
  const value = raw.trim();
  if (value === '(null)') return null;
  if (!value.startsWith('"')) return value || null;
  try {
    return String(JSON.parse(value)) || null;
  } catch {
    return null;
  }
}

/**
 * Groups `mdls` output into one record per bundle, keyed by its own `kMDItemPath`.
 *
 * `mdls` prints the requested attributes in its own order — alphabetical, so
 * `kMDItemPath` comes last — and repeats that block for every file. A repeated
 * attribute is therefore what starts the next file's record; treating `kMDItemPath`
 * as the delimiter would attach each app's name and bundle id to the previous path.
 */
function readSpotlightAttributes(bundlePaths: string[]): Map<string, InstalledApp> {
  const byPath = new Map<string, InstalledApp>();
  if (bundlePaths.length === 0) return byPath;
  let output: string;
  try {
    output = execFileSync(
      '/usr/bin/mdls',
      [...MDLS_ATTRIBUTES.flatMap((attribute) => ['-name', attribute]), '--', ...bundlePaths],
      { encoding: 'utf8', maxBuffer: 32 * 1024 * 1024, stdio: ['ignore', 'pipe', 'ignore'] }
    );
  } catch (error) {
    console.error('Failed to read installed application metadata from Spotlight:', error);
    return byPath;
  }

  let current: { path?: string; bundleId?: string | null; name?: string | null } = {};
  let seen = new Set<string>();
  const flush = () => {
    // A bundle Spotlight does not know reports no path; the caller reads its plist.
    if (current.path) {
      const canonical = current.path.startsWith(DATA_VOLUME_PREFIX)
        ? current.path.slice(DATA_VOLUME_PREFIX.length)
        : current.path;
      byPath.set(canonical, {
        name: current.name || path.basename(canonical, '.app'),
        bundleId: current.bundleId ?? null,
        path: canonical,
      });
    }
    current = {};
    seen = new Set();
  };

  for (const line of output.split('\n')) {
    const separator = line.indexOf('=');
    if (separator === -1) continue;
    const attribute = line.slice(0, separator).trim();
    const value = parseMdlsValue(line.slice(separator + 1));
    if (seen.has(attribute)) flush();
    if (attribute === 'kMDItemPath') current.path = value ?? undefined;
    else if (attribute === 'kMDItemCFBundleIdentifier') current.bundleId = value;
    else if (attribute === 'kMDItemDisplayName') current.name = value;
    else continue;
    seen.add(attribute);
  }
  flush();
  return byPath;
}

function readBundleIdFromInfoPlist(bundlePath: string): string | null {
  try {
    const value = execFileSync(
      '/usr/bin/plutil',
      [
        '-extract',
        'CFBundleIdentifier',
        'raw',
        '-o',
        '-',
        '--',
        `${bundlePath}/Contents/Info.plist`,
      ],
      { encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'] }
    ).trim();
    return value || null;
  } catch {
    return null;
  }
}

function scanInstalledApps(): InstalledApp[] {
  const bundlePaths = applicationBundlePaths();
  const spotlight = readSpotlightAttributes(bundlePaths);
  return bundlePaths.map((bundlePath) => {
    const indexed = spotlight.get(bundlePath);
    return {
      name: indexed?.name || path.basename(bundlePath, '.app'),
      // The recorder compares the running app's bundle id, so an entry without one
      // never matches; an indexed row missing the attribute still reads its plist.
      bundleId: indexed?.bundleId ?? readBundleIdFromInfoPlist(bundlePath),
      path: bundlePath,
    };
  });
}

let lastScannedApps: InstalledApp[] | null = null;

/**
 * Installed applications from the most recent scan, scanning when there is none.
 *
 * The picker's enumeration rescans, so an app installed after launch is offered; name
 * resolution reuses that scan because the legacy migration resolves one name per
 * configured app and each scan shells out to `mdls`.
 */
export function listInstalledApps(): InstalledApp[] {
  lastScannedApps ??= scanInstalledApps();
  return lastScannedApps;
}

/**
 * Bundle identifier for a display name, used to upgrade name-only legacy entries.
 * Returns null when no installed bundle carries that name.
 */
export function resolveInstalledAppBundleId(name: string): string | null {
  const wanted = name.trim().toLowerCase();
  if (!wanted) return null;
  for (const app of listInstalledApps()) {
    if (app.name.trim().toLowerCase() === wanted) return app.bundleId;
    if (path.basename(app.path, '.app').toLowerCase() === wanted) return app.bundleId;
  }
  return null;
}

/** One row in the settings app picker. */
export type InstalledAppOption = {
  name: string;
  bundleId: string | null;
  /** PNG data URL of the bundle icon; null when the icon could not be read. */
  iconDataUrl: string | null;
};

/** Reads one bundle's icon as a data URL; null when the bundle has no readable icon. */
export type AppIconReader = (bundlePath: string) => Promise<string | null>;

/**
 * Installed applications with their bundle icons.
 *
 * The list is scanned on every call: an app installed after launch — a password
 * manager, say — must be offered to the picker, or the user cannot exclude it until
 * the next restart. The icon reader caches, because reading icons is the expensive
 * part and the scan is what has to be fresh.
 */
export function listInstalledAppOptions(readAppIcon: AppIconReader): Promise<InstalledAppOption[]> {
  lastScannedApps = scanInstalledApps();
  return Promise.all(
    lastScannedApps.map(async (installed) => ({
      name: installed.name,
      bundleId: installed.bundleId,
      iconDataUrl: await readAppIcon(installed.path),
    }))
  );
}
