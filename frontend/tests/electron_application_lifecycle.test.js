const assert = require('assert');
const { test } = require('node:test');

const {
  installDesktopApplicationLifecycle,
} = require('../electron/dist/main_runtime/applicationLifecycle.js');

function createFakeApp() {
  const listeners = new Map();
  const protocolCalls = [];
  return {
    listeners,
    protocolCalls,
    isQuitting: undefined,
    on(event, listener) {
      listeners.set(event, listener);
    },
    whenReady: () => Promise.resolve(),
    setAsDefaultProtocolClient: (...args) => protocolCalls.push(args),
    quit() {
      this.quitCalls = (this.quitCalls || 0) + 1;
    },
  };
}

test('application lifecycle orders foreground startup before background services', async () => {
  const app = createFakeApp();
  const calls = [];
  installDesktopApplicationLifecycle({
    app,
    protocol: 'pantaray',
    argv: ['/electron', '/app/main.js'],
    execPath: '/electron',
    platform: 'linux',
    isDefaultApp: false,
    initializeTray: () => calls.push('tray'),
    initializeUpdater: () => calls.push('updater'),
    rebuildAppMenu: () => calls.push('menu'),
    registerIpc: () => calls.push('ipc'),
    createMainWindow: () => calls.push('window'),
    initializeGlobalShortcut: () => calls.push('shortcut'),
    handleStartupArgs: () => calls.push('deep-link'),
    startBackgroundRuntime: () => calls.push('background'),
    activate: () => calls.push('activate'),
    shutdown: async () => { calls.push('shutdown'); },
    showMainWindowCreateError: () => calls.push('window-error'),
    showStartupError: () => calls.push('startup-error'),
    logger: null,
  });

  await new Promise((resolve) => setImmediate(resolve));

  assert.deepEqual(calls, [
    'tray',
    'updater',
    'menu',
    'ipc',
    'window',
    'shortcut',
    'deep-link',
    'background',
  ]);
  assert.deepEqual(app.protocolCalls, [['pantaray']]);

  app.listeners.get('before-quit')({ preventDefault() {} });
  app.listeners.get('activate')();
  app.listeners.get('window-all-closed')();
  assert.equal(app.isQuitting, true);
  assert.equal(app.quitCalls, 1);
  assert.deepEqual(calls.slice(-2), ['shutdown', 'activate']);
});

test('application lifecycle reports the failing startup stage and does not start background work', async () => {
  const app = createFakeApp();
  const events = [];
  let startupError = null;
  installDesktopApplicationLifecycle({
    app,
    protocol: 'pantaray',
    argv: ['/electron'],
    execPath: '/electron',
    platform: 'darwin',
    isDefaultApp: false,
    initializeTray: () => {},
    initializeUpdater: () => {},
    rebuildAppMenu: () => {},
    registerIpc: () => {
      throw new Error('IPC failed');
    },
    createMainWindow: () => assert.fail('window must not be created'),
    initializeGlobalShortcut: () => assert.fail('shortcut must not initialize'),
    handleStartupArgs: () => assert.fail('deep link must not run'),
    startBackgroundRuntime: () => assert.fail('background must not start'),
    activate: () => {},
    shutdown: () => {},
    showMainWindowCreateError: () => {},
    showStartupError: (error) => {
      startupError = error;
    },
    logger: {
      error: (event, payload) => events.push([event, payload]),
    },
  });

  await new Promise((resolve) => setImmediate(resolve));

  assert.match(startupError.message, /IPC failed/);
  assert.equal(events[0][0], 'APP_STARTUP_ERR');
  assert.equal(events[0][1].stage, 'ipc-registration');
});

test('application lifecycle disables a failed shortcut without blocking remaining startup', async () => {
  const app = createFakeApp();
  const calls = [];
  const events = [];
  installDesktopApplicationLifecycle({
    app,
    protocol: 'pantaray',
    argv: ['/electron'],
    execPath: '/electron',
    platform: 'darwin',
    isDefaultApp: false,
    initializeTray: () => {},
    initializeUpdater: () => {},
    rebuildAppMenu: () => {},
    registerIpc: () => {},
    createMainWindow: () => {},
    initializeGlobalShortcut: () => {
      throw new Error('shortcut unavailable');
    },
    handleStartupArgs: () => calls.push('deep-link'),
    startBackgroundRuntime: () => calls.push('background'),
    activate: () => {},
    shutdown: () => {},
    showMainWindowCreateError: () => {},
    showStartupError: () => calls.push('startup-error'),
    logger: { error: (event, payload) => events.push([event, payload]) },
  });

  await new Promise((resolve) => setImmediate(resolve));

  assert.deepEqual(calls, ['deep-link', 'background']);
  assert.deepEqual(
    events.map(([event]) => event),
    ['GLOBAL_SHORTCUT_INIT_ERR']
  );
});
