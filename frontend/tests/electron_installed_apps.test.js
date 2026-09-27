const assert = require('node:assert/strict');
const Module = require('node:module');
const { test } = require('node:test');

const TARGET = require.resolve('../electron/dist/privacy/installedApps');

function dirent(name, isDirectory) {
  return { name, isDirectory: () => isDirectory };
}

/**
 * Loads the module with a fake filesystem and fake `mdls` / `plutil`.
 *
 * `tree` maps a directory path to its entries; `spotlight` maps a bundle path to the
 * attributes Spotlight would answer with (omit `bundleId` to simulate a row without
 * `kMDItemCFBundleIdentifier`); `plists` maps a bundle path to its CFBundleIdentifier.
 */
function loadInstalledApps({ tree = {}, spotlight = {}, plists = {} }) {
  const plutilCalls = [];
  delete require.cache[TARGET];
  const load = Module._load;
  Module._load = function (request, parent, isMain) {
    if (request === 'node:fs')
      return {
        readdirSync: (directory) => {
          const entries = tree[directory];
          if (!entries) throw new Error(`ENOENT: ${directory}`);
          return entries;
        },
      };
    if (request === 'node:os') return { homedir: () => '/Users/tester' };
    if (request === 'node:child_process')
      return {
        execFileSync: (binary, args) => {
          if (binary === '/usr/bin/mdls') {
            const paths = args.slice(args.indexOf('--') + 1);
            // Real `mdls` prints the requested attributes alphabetically, so
            // kMDItemPath is the LAST line of each file's block, not the first.
            return paths
              .filter((bundlePath) => spotlight[bundlePath])
              .map((bundlePath) => {
                const row = spotlight[bundlePath];
                const bundleId = 'bundleId' in row ? JSON.stringify(row.bundleId) : '(null)';
                return [
                  `kMDItemCFBundleIdentifier = ${bundleId}`,
                  `kMDItemDisplayName        = ${JSON.stringify(row.name)}`,
                  `kMDItemPath               = ${JSON.stringify(bundlePath)}`,
                ].join('\n');
              })
              .join('\n');
          }
          const plistPath = args[args.length - 1];
          plutilCalls.push(plistPath);
          const bundlePath = plistPath.replace('/Contents/Info.plist', '');
          const value = plists[bundlePath];
          if (!value) throw new Error(`no Info.plist: ${plistPath}`);
          return `${value}\n`;
        },
      };
    return load.call(this, request, parent, isMain);
  };
  try {
    return { module: require(TARGET), plutilCalls };
  } finally {
    Module._load = load;
    delete require.cache[TARGET];
  }
}

test('installedApps: a Spotlight row without a bundle id falls back to Info.plist', () => {
  const loaded = loadInstalledApps({
    tree: {
      '/Applications': [dirent('Figma.app', true)],
      '/System/Applications': [],
      '/Users/tester/Applications': [],
    },
    spotlight: { '/Applications/Figma.app': { name: 'Figma' } },
    plists: { '/Applications/Figma.app': 'com.figma.Desktop' },
  });

  // The recorder matches on bundle id, so exposing bundleId: null would silently
  // record an app the user excluded.
  assert.deepEqual(loaded.module.listInstalledApps(), [
    { name: 'Figma', bundleId: 'com.figma.Desktop', path: '/Applications/Figma.app' },
  ]);
  assert.deepEqual(loaded.plutilCalls, ['/Applications/Figma.app/Contents/Info.plist']);
});

test('installedApps: Spotlight attributes stay with their own bundle', () => {
  const loaded = loadInstalledApps({
    tree: {
      '/Applications': [dirent('Calculator.app', true), dirent('Chess.app', true)],
      '/System/Applications': [],
      '/Users/tester/Applications': [],
    },
    spotlight: {
      '/Applications/Calculator.app': { name: '計算機', bundleId: 'com.apple.calculator' },
      '/Applications/Chess.app': { name: 'チェス', bundleId: 'com.apple.Chess' },
    },
  });

  // Attaching one app's bundle id to another would exclude the wrong app while
  // continuing to record the one the user picked.
  assert.deepEqual(loaded.module.listInstalledApps(), [
    { name: '計算機', bundleId: 'com.apple.calculator', path: '/Applications/Calculator.app' },
    { name: 'チェス', bundleId: 'com.apple.Chess', path: '/Applications/Chess.app' },
  ]);
  assert.deepEqual(loaded.plutilCalls, []);
});

test('installedApps: application bundles inside vendor folders are enumerated', () => {
  const loaded = loadInstalledApps({
    tree: {
      '/Applications': [dirent('Adobe Photoshop 2026', true), dirent('Utilities', true)],
      '/Applications/Adobe Photoshop 2026': [
        dirent('Adobe Photoshop.app', true),
        dirent('Presets', true),
      ],
      '/Applications/Utilities': [dirent('Terminal.app', true)],
      // Never descended into: a bundle's own Contents holds helper .app bundles.
      '/Applications/Adobe Photoshop 2026/Adobe Photoshop.app': [dirent('Helper.app', true)],
      '/System/Applications': [],
      '/Users/tester/Applications': [],
    },
    spotlight: {
      '/Applications/Adobe Photoshop 2026/Adobe Photoshop.app': {
        name: 'Adobe Photoshop',
        bundleId: 'com.adobe.Photoshop',
      },
      '/Applications/Utilities/Terminal.app': {
        name: 'Terminal',
        bundleId: 'com.apple.Terminal',
      },
    },
  });

  assert.deepEqual(
    loaded.module.listInstalledApps().map((app) => app.path),
    [
      '/Applications/Adobe Photoshop 2026/Adobe Photoshop.app',
      '/Applications/Utilities/Terminal.app',
    ]
  );
  assert.equal(
    loaded.module.resolveInstalledAppBundleId('Adobe Photoshop'),
    'com.adobe.Photoshop'
  );
});
