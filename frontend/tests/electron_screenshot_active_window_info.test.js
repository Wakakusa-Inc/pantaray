const assert = require('node:assert/strict');
const Module = require('node:module');
const { test } = require('node:test');

function loadScreenshotWithElectron(electronMock) {
  const sourcePath = require.resolve('../electron/screenshot.js');
  delete require.cache[sourcePath];
  const originalLoad = Module._load;
  Module._load = function patchedLoad(request, parent, isMain) {
    if (request === 'electron') return electronMock;
    return originalLoad.call(this, request, parent, isMain);
  };
  try {
    return require(sourcePath);
  } finally {
    Module._load = originalLoad;
    delete require.cache[sourcePath];
  }
}

test('probeBrowserUrlForApp queries only the described supported browser', async () => {
  const commands = [];
  const { probeBrowserUrlForApp } = loadScreenshotWithElectron({
    systemPreferences: {
      getMediaAccessStatus: () => 'denied',
      isTrustedAccessibilityClient: () => true,
    },
  });

  const chrome = await probeBrowserUrlForApp(async (command) => {
    commands.push(command);
    return { stdout: 'https://chrome.example/path\tChrome Page\n' };
  }, 'Google Chrome');
  const safari = await probeBrowserUrlForApp(async (command) => {
    commands.push(command);
    return { stdout: 'https://safari.example/path\tSafari Page\n' };
  }, 'Safari');
  const unsupported = await probeBrowserUrlForApp(async (command) => {
    commands.push(command);
    return { stdout: 'https://unexpected.example\n' };
  }, 'Google Chrome Canary');

  assert.deepEqual(chrome, {
    url: 'https://chrome.example/path',
    appName: 'Google Chrome',
    windowName: 'Chrome Page',
    error: null,
  });
  assert.deepEqual(safari, {
    url: 'https://safari.example/path',
    appName: 'Safari',
    windowName: 'Safari Page',
    error: null,
  });
  assert.deepEqual(unsupported, {
    url: null,
    appName: 'Google Chrome Canary',
    windowName: null,
    error: 'Unsupported browser app.',
  });
  assert.equal(commands.length, 2);
  assert.match(commands[0], /tell application "Google Chrome"/);
  assert.doesNotMatch(commands[0], /System Events|Safari/);
  assert.match(commands[1], /tell application "Safari"/);
  assert.doesNotMatch(commands[1], /System Events|Google Chrome/);
});

test('captureActiveWindowInfo preserves the longer AXTitle for advisory consumers', async () => {
  const commands = [];
  const { captureActiveWindowInfo } = loadScreenshotWithElectron({
    BrowserWindow: {
      getAllWindows: () => [],
      getFocusedWindow: () => null,
    },
    systemPreferences: {
      getMediaAccessStatus: () => 'denied',
      isTrustedAccessibilityClient: () => true,
    },
  });

  const result = await captureActiveWindowInfo(async (command) => {
    commands.push(command);
    return { stdout: 'Slack\tgeneral (Workspace) - Slack\n' };
  }, null);

  assert.deepEqual(result, {
    name: 'Slack',
    title: 'general (Workspace) - Slack',
  });
  assert.equal(commands.length, 1);
  assert.match(commands[0], /appName & "\\t" & winTitle/);
});
