const assert = require('assert');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { test } = require('node:test');

const { createCapturePrivacyManager } = require('../electron/dist/privacy/capturePrivacy.js');
const { resolveScopedSettingsPath } = require('../electron/dist/settings/scope.js');

const BUNDLE_IDS = {
  slack: 'com.tinyspeck.slackmacgap',
  safari: 'com.apple.Safari',
};

function resolveAppBundleId(name) {
  return BUNDLE_IDS[String(name).toLowerCase()] ?? null;
}

function mkdtemp() {
  return fs.mkdtempSync(path.join(os.tmpdir(), 'pantaray-privacy-'));
}

function settingsPathFor(dir, userId = null) {
  return resolveScopedSettingsPath({
    userDataDir: dir,
    userId,
    fileName: 'capture-privacy-settings.json',
  });
}

function createManager(dir, initialUserId) {
  return createCapturePrivacyManager({ userDataDir: dir, initialUserId, resolveAppBundleId });
}

test('capturePrivacy: keeps stored IDE rules when the filter dialog omits them', () => {
  const mgr = createManager(mkdtemp());
  mgr.updateIdeFileRules({
    mode: 'on',
    onFileNameUnavailable: 'block',
    sensitivePresets: { blockEnvFiles: true },
  });

  const saved = mgr.updateCaptureSettings({
    version: 2,
    apps: { mode: 'include_only', entries: [{ name: 'Slack', bundleId: BUNDLE_IDS.slack }] },
    websites: { mode: 'exclude', hosts: ['example.com'] },
  });

  assert.strictEqual(saved.ideFileRules.onFileNameUnavailable, 'block');
  assert.deepStrictEqual(saved.apps.entries, [{ name: 'Slack', bundleId: BUNDLE_IDS.slack }]);
});

test('capturePrivacy: persistence failure leaves capture settings unchanged', () => {
  const dir = mkdtemp();
  const mgr = createManager(dir);
  const initialSettings = mgr.updateCaptureSettings({
    version: 2,
    apps: { mode: 'exclude', entries: [{ name: 'Safari', bundleId: BUNDLE_IDS.safari }] },
    websites: { mode: 'exclude', hosts: [] },
  });
  const scopeDirectory = path.dirname(settingsPathFor(dir));
  fs.rmSync(scopeDirectory, { recursive: true });
  fs.writeFileSync(scopeDirectory, 'not-a-directory', 'utf8');

  assert.throws(() =>
    mgr.updateCaptureSettings({
      version: 2,
      apps: { mode: 'include_only', entries: [] },
      websites: { mode: 'exclude', hosts: [] },
    })
  );
  assert.deepStrictEqual(mgr.getCaptureSettings(), initialSettings);
});

test('capturePrivacy: settings are isolated by user scope', () => {
  const dir = mkdtemp();
  const mgr = createManager(dir, 'user_a');
  mgr.updateCaptureSettings({
    version: 2,
    apps: { mode: 'include_only', entries: [{ name: 'Slack', bundleId: BUNDLE_IDS.slack }] },
    websites: { mode: 'include_only', hosts: ['example.com'] },
  });

  mgr.setSettingsScope('user_b');
  assert.deepStrictEqual(mgr.getCaptureSettings().apps, { mode: 'exclude', entries: [] });
  assert.deepStrictEqual(mgr.getCaptureSettings().websites, { mode: 'exclude', hosts: [] });

  mgr.setSettingsScope('user_a');
  assert.strictEqual(mgr.getCaptureSettings().apps.mode, 'include_only');
  assert.deepStrictEqual(mgr.getCaptureSettings().websites.hosts, ['example.com']);
});

test('capturePrivacy: a legacy allow list becomes include-only apps with resolved bundle ids', () => {
  const dir = mkdtemp();
  fs.writeFileSync(
    settingsPathFor(dir),
    JSON.stringify({
      mode: 'allow_only',
      apps: [
        { name: 'Excluded App', enabled: false },
        { name: 'Safari', enabled: true },
        { name: 'Retired App', mode: 'all' },
        // The legacy normalizer mapped `workspaces` to `all` before reading `enabled`.
        { name: 'Slack', mode: 'workspaces', enabled: false },
      ],
      browserUrlRules: {
        mode: 'rules',
        defaultPolicy: 'block_by_default',
        onUrlUnavailable: 'allow',
        sensitivePresets: { blockAuth: true, blockPayments: true },
        allowList: [
          { id: 'r1', host: 'Example.com', pathPrefix: '', matchSubdomains: true },
          // The legacy editor stored a bare domain as pathPrefix '/'.
          { id: 'r6', host: 'root.example.com', pathPrefix: '/', matchSubdomains: true },
          // Narrower than a host-wide entry: migrating either as one would record
          // pages the legacy rules did not allow.
          { id: 'r2', host: 'docs.example.net', pathPrefix: '/docs', matchSubdomains: true },
          { id: 'r3', host: 'example.org', pathPrefix: '', matchSubdomains: false },
          // The recorder denies a block-list match before it reads the allow list.
          { id: 'r4', host: 'blocked.example.com', pathPrefix: '', matchSubdomains: true },
        ],
        blockList: [
          { id: 'r5', host: 'Blocked.example.com', pathPrefix: '', matchSubdomains: false },
        ],
      },
    })
  );

  const settings = createManager(dir).getCaptureSettings();

  assert.deepStrictEqual(settings.apps, {
    mode: 'include_only',
    entries: [
      { name: 'Safari', bundleId: BUNDLE_IDS.safari },
      { name: 'Retired App', bundleId: null },
      { name: 'Slack', bundleId: BUNDLE_IDS.slack },
    ],
  });
  // block_by_default recorded only the allow list, and the new filter is host-wide, so
  // only the allow entries that already covered a whole host survive; a blocked host is
  // dropped as well because the recorder denied it before reading the allow list.
  assert.deepStrictEqual(settings.websites, {
    mode: 'include_only',
    hosts: ['example.com', 'root.example.com'],
  });
  // The migration is written back, so the next load reads version 2 directly.
  assert.strictEqual(JSON.parse(fs.readFileSync(settingsPathFor(dir), 'utf8')).version, 2);
});

test('capturePrivacy: legacy all_sites migrates to exclude with the block list', () => {
  const dir = mkdtemp();
  fs.writeFileSync(
    settingsPathFor(dir),
    JSON.stringify({
      mode: 'allow_only',
      apps: [{ name: 'Slack', mode: 'off' }],
      browserUrlRules: {
        mode: 'all_sites',
        defaultPolicy: 'allow_by_default',
        onUrlUnavailable: 'allow',
        allowList: [],
        blockList: [{ id: 'r1', host: 'private.example.com', pathPrefix: '', matchSubdomains: false }],
      },
    })
  );

  const settings = createManager(dir).getCaptureSettings();

  assert.deepStrictEqual(settings.apps, { mode: 'exclude', entries: [] });
  // The recorder denies a block-list match before the `all_sites` short-circuit, so
  // those hosts were not being recorded and must stay excluded after the upgrade.
  assert.deepStrictEqual(settings.websites, {
    mode: 'exclude',
    hosts: ['private.example.com'],
  });
});

test('capturePrivacy: legacy browser rules that were off migrate without widening capture', () => {
  const dir = mkdtemp();
  fs.writeFileSync(
    settingsPathFor(dir),
    JSON.stringify({
      mode: 'allow_only',
      apps: [{ name: 'Safari', mode: 'all' }],
      browserUrlRules: {
        mode: 'off',
        defaultPolicy: 'block_by_default',
        // Switching to `off` never cleared the lists, so both are stale here.
        allowList: [{ id: 'r1', host: 'intranet.example.com', pathPrefix: '', matchSubdomains: true }],
        blockList: [{ id: 'r2', host: 'blocked.example.com', pathPrefix: '', matchSubdomains: true }],
      },
    })
  );

  assert.deepStrictEqual(createManager(dir).getCaptureSettings().websites, {
    mode: 'include_only',
    hosts: [],
  });
});

test('capturePrivacy: legacy allow-by-default rules migrate to exclude with the block list', () => {
  const dir = mkdtemp();
  fs.writeFileSync(
    settingsPathFor(dir),
    JSON.stringify({
      mode: 'allow_only',
      apps: [],
      browserUrlRules: {
        mode: 'rules',
        defaultPolicy: 'allow_by_default',
        allowList: [],
        blockList: [{ id: 'r1', host: 'Bank.example.com', pathPrefix: '', matchSubdomains: true }],
      },
    })
  );

  // `rules` + allow-by-default recorded every site except the block list; migrating to
  // include-only with an empty allow list would silently stop recording every site.
  assert.deepStrictEqual(createManager(dir).getCaptureSettings().websites, {
    mode: 'exclude',
    hosts: ['bank.example.com'],
  });
});

test('capturePrivacy: unreadable settings record nothing instead of everything', () => {
  const dir = mkdtemp();
  fs.writeFileSync(settingsPathFor(dir), '{ this is not json');

  // Whether recording is on lives in another file, so the recorder can resume while
  // this one is unreadable; the `exclude` default would then record everything.
  assert.deepStrictEqual(createManager(dir).getCaptureSettings(), {
    version: 2,
    apps: { mode: 'include_only', entries: [] },
    websites: { mode: 'include_only', hosts: [] },
    ideFileRules: { mode: 'on', onFileNameUnavailable: 'allow', sensitivePresets: { blockEnvFiles: true } },
  });
});
