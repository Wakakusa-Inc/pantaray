const assert = require('assert');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { test } = require('node:test');

const ui = require('../electron/dist/ui/uiLanguage.js');
const { resolveScopedSettingsPath } = require('../electron/dist/settings/scope.js');

function tmpFile() {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'pantaray-ui-lang-'));
  return path.join(dir, 'ui-settings.json');
}

test('uiLanguage: normalizeUiLanguage', () => {
  assert.equal(ui.normalizeUiLanguage('ja'), 'ja');
  assert.equal(ui.normalizeUiLanguage('en'), 'en');
  assert.equal(ui.normalizeUiLanguage('zzz'), 'en');
  assert.equal(ui.normalizeUiLanguage(null), 'en');
});

test('uiLanguage: defaultUiLanguage follows the app locale before user preference exists', () => {
  assert.equal(ui.defaultUiLanguage('ja-JP'), 'ja');
  assert.equal(ui.defaultUiLanguage('ja'), 'ja');
  assert.equal(ui.defaultUiLanguage('en-US'), 'en');
});

test('uiLanguage: saveUiLanguage + loadUiLanguage roundtrip', () => {
  const p = tmpFile();
  ui.saveUiLanguage(p, 'ja');
  const loaded = ui.loadUiLanguage(p, 'en-US');
  assert.equal(loaded, 'ja');
});

test('uiLanguage: loadUiLanguage uses default when file is missing', () => {
  const p = tmpFile();

  assert.equal(ui.loadUiLanguage(p, 'ja-JP'), 'ja');
});

test('uiLanguage: loadUiLanguage rejects broken settings files', () => {
  const p = tmpFile();

  fs.writeFileSync(p, '{ broken', 'utf8');

  assert.throws(() => ui.loadUiLanguage(p, 'en-US'), SyntaxError);
});

test('uiLanguage: saveUiLanguage surfaces write failures', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'pantaray-ui-lang-fail-'));
  const parentFile = path.join(dir, 'not-a-directory');
  fs.writeFileSync(parentFile, 'x', 'utf8');

  assert.throws(() => ui.saveUiLanguage(path.join(parentFile, 'ui-settings.json'), 'ja'));
});

test('uiLanguage: broadcastUiLanguage sends to all windows best-effort', () => {
  const sent = [];
  const windows = [
    {
      isDestroyed: () => false,
      webContents: {
        send: (channel, payload) => sent.push({ channel, payload }),
      },
    },
    {
      isDestroyed: () => true,
      webContents: {
        send: () => sent.push({ channel: 'should-not', payload: 'x' }),
      },
    },
  ];
  ui.broadcastUiLanguage(windows, 'ja');
  assert.deepEqual(sent, [{ channel: 'ui:languageChanged', payload: 'ja' }]);
});

test('uiLanguage: scoped paths isolate users and ignore legacy shared file', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'pantaray-ui-lang-scope-'));
  const legacy = path.join(dir, 'ui-settings.json');
  fs.writeFileSync(legacy, JSON.stringify({ ui_language: 'ja' }, null, 2), 'utf8');

  const pathA = resolveScopedSettingsPath({
    userDataDir: dir,
    userId: 'user_a',
    fileName: 'ui-settings.json',
  });
  const pathB = resolveScopedSettingsPath({
    userDataDir: dir,
    userId: 'user_b',
    fileName: 'ui-settings.json',
  });

  // 共有レガシーファイルがあっても、スコープファイルが無ければ locale 由来の既定値を返す
  assert.equal(ui.loadUiLanguage(pathA, 'ja-JP'), 'ja');
  assert.equal(ui.loadUiLanguage(pathB, 'ja-JP'), 'ja');

  ui.saveUiLanguage(pathA, 'ja');
  ui.saveUiLanguage(pathB, 'en');

  assert.equal(ui.loadUiLanguage(pathA, 'en-US'), 'ja');
  assert.equal(ui.loadUiLanguage(pathB, 'ja-JP'), 'en');
});
