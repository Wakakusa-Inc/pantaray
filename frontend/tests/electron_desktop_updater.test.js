const assert = require('node:assert/strict');
const Module = require('node:module');
const { test } = require('node:test');

function withDesktopUpdaterMocks({ app, autoUpdater, timers }, fn) {
  const sourcePath = require.resolve('../electron/dist/update/desktopUpdater.js');
  delete require.cache[sourcePath];
  const originalLoad = Module._load;
  const originalSetTimeout = global.setTimeout;
  Module._load = function patchedLoad(request, parent, isMain) {
    if (request === 'electron') {
      return { app };
    }
    if (request === 'electron-updater') {
      return { autoUpdater };
    }
    return originalLoad.call(this, request, parent, isMain);
  };
  global.setTimeout = timers.setTimeout;
  try {
    return fn(require(sourcePath));
  } finally {
    Module._load = originalLoad;
    global.setTimeout = originalSetTimeout;
    delete require.cache[sourcePath];
  }
}

function createAutoUpdater() {
  return {
    autoDownload: false,
    autoInstallOnAppQuit: false,
    on: () => {},
    setFeedURL: () => {},
    checkForUpdates: async () => {},
    quitAndInstall: () => {},
  };
}

test('quitAndInstall runs shutdown hook before applying the downloaded update', () => {
  const calls = [];
  const app = {
    isPackaged: true,
    getVersion: () => '0.1.1',
    exit: (code) => calls.push(['exit', code]),
  };
  const autoUpdater = createAutoUpdater();
  autoUpdater.quitAndInstall = (isSilent, isForceRunAfter) => {
    calls.push(['quitAndInstall', isSilent, isForceRunAfter]);
  };
  const timers = {
    setTimeout: (callback, delayMs) => {
      calls.push(['timer', delayMs]);
      callback();
      return 1;
    },
  };

  const logs = [];
  withDesktopUpdaterMocks({ app, autoUpdater, timers }, ({ createDesktopUpdater }) => {
    const updater = createDesktopUpdater({
      logger: {
        info: (name, payload) => logs.push(['info', name, payload]),
        warn: (name, payload) => logs.push(['warn', name, payload]),
        error: (name, payload) => logs.push(['error', name, payload]),
      },
      beforeQuitAndInstall: () => calls.push(['beforeQuitAndInstall']),
    });

    updater.quitAndInstall();
  });

  assert.deepEqual(calls, [
    ['beforeQuitAndInstall'],
    ['quitAndInstall', false, true],
    ['timer', 6000],
    ['exit', 0],
  ]);
  assert.equal(logs[0][1], 'AUTO_UPDATE_QUIT_INSTALL_REQUESTED');
  assert.equal(logs[1][1], 'AUTO_UPDATE_QUIT_FALLBACK');
});

test('start checks immediately on a packaged build without any auth token and schedules rechecks', () => {
  const calls = [];
  const app = { isPackaged: true, getVersion: () => '0.1.1', exit: () => {} };
  const autoUpdater = createAutoUpdater();
  autoUpdater.checkForUpdates = async () => {
    calls.push('checkForUpdates');
  };
  const intervals = [];
  const originalSetInterval = global.setInterval;
  global.setInterval = (callback, delayMs) => {
    intervals.push(delayMs);
    return 1;
  };
  try {
    withDesktopUpdaterMocks({ app, autoUpdater, timers: { setTimeout } }, ({ createDesktopUpdater }) => {
      const updater = createDesktopUpdater({ logger: null });
      updater.start();
      updater.start();
    });
  } finally {
    global.setInterval = originalSetInterval;
  }
  assert.deepEqual(calls, ['checkForUpdates']);
  assert.deepEqual(intervals, [6 * 60 * 60 * 1000]);
  assert.equal(autoUpdater.allowPrerelease, false);
  assert.equal(autoUpdater.requestHeaders, undefined);
});

test('packaged dev builds have no update feed and never check', () => {
  const calls = [];
  const app = { isPackaged: true, getVersion: () => '0.1.1-dev.3+abc1234', exit: () => {} };
  const autoUpdater = createAutoUpdater();
  autoUpdater.checkForUpdates = async () => {
    calls.push('checkForUpdates');
  };
  const logs = [];
  withDesktopUpdaterMocks(
    { app, autoUpdater, timers: { setTimeout } },
    ({ createDesktopUpdater, hasUpdateFeed, resolveChannelFromVersion }) => {
      assert.equal(hasUpdateFeed(), false);
      assert.deepEqual(
        ['0.1.1', '0.1.1-test.3', '0.1.1-rc.1', '0.1.1-dev.3+abc1234'].map(resolveChannelFromVersion),
        ['stable', 'test', null, null],
      );
      const updater = createDesktopUpdater({ logger: { info: (name) => logs.push(name) } });
      updater.start();
      return updater.checkForUpdates('manual');
    },
  );
  assert.deepEqual(calls, []);
  assert.equal(autoUpdater.allowPrerelease, false);
  assert.ok(logs.includes('AUTO_UPDATE_DISABLED'));
});

test('test-channel versions accept prereleases and unpackaged builds never check', () => {
  const calls = [];
  const app = { isPackaged: false, getVersion: () => '0.1.1-test.3', exit: () => {} };
  const autoUpdater = createAutoUpdater();
  autoUpdater.checkForUpdates = async () => {
    calls.push('checkForUpdates');
  };
  withDesktopUpdaterMocks({ app, autoUpdater, timers: { setTimeout } }, ({ createDesktopUpdater }) => {
    const updater = createDesktopUpdater({ logger: null });
    updater.start();
    return updater.checkForUpdates('manual');
  });
  assert.equal(autoUpdater.allowPrerelease, true);
  assert.deepEqual(calls, []);
});
