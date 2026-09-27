const assert = require('node:assert/strict');
const test = require('node:test');
const ts = require('typescript');

function loadModule() {
  const sourcePath = require.resolve('../electron/src/windows/windowVisibility.ts');
  const source = require('node:fs').readFileSync(sourcePath, 'utf8');
  const output = ts.transpileModule(source, {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2020,
      esModuleInterop: true,
    },
  }).outputText;
  const module = { exports: {} };
  const fn = new Function('require', 'module', 'exports', output);
  fn(require, module, module.exports);
  return module.exports;
}

function createWindowState(overrides = {}) {
  const calls = [];
  const state = {
    destroyed: false,
    minimized: false,
    visible: true,
    ...overrides,
  };
  return {
    calls,
    win: {
      isDestroyed: () => state.destroyed,
      isMinimized: () => state.minimized,
      restore: () => {
        calls.push('restore');
        state.minimized = false;
        state.visible = true;
      },
      isVisible: () => state.visible,
      show: () => {
        calls.push('show');
        state.visible = true;
      },
      focus: () => {
        calls.push('focus');
      },
    },
  };
}

test('restoreAndFocusWindow restores minimized windows before focusing', () => {
  const { restoreAndFocusWindow } = loadModule();
  const { calls, win } = createWindowState({ minimized: true, visible: false });

  assert.equal(restoreAndFocusWindow(win), true);
  assert.deepEqual(calls, ['restore', 'focus']);
});

test('restoreAndFocusWindow shows hidden windows before focusing', () => {
  const { restoreAndFocusWindow } = loadModule();
  const { calls, win } = createWindowState({ visible: false });

  assert.equal(restoreAndFocusWindow(win), true);
  assert.deepEqual(calls, ['show', 'focus']);
});

test('restoreAndFocusWindow ignores missing and destroyed windows', () => {
  const { restoreAndFocusWindow } = loadModule();
  const { calls, win } = createWindowState({ destroyed: true });

  assert.equal(restoreAndFocusWindow(null), false);
  assert.equal(restoreAndFocusWindow(win), false);
  assert.deepEqual(calls, []);
});

test('ensureMainWindowFocused restores an existing main window instead of creating one', () => {
  const { ensureMainWindowFocused } = loadModule();
  const { calls, win } = createWindowState({ visible: false, minimized: true });
  let created = 0;

  // The window it returns is the one a caller may still send something to.
  assert.equal(
    ensureMainWindowFocused({ getMainWindow: () => win, createMainWindow: () => created++ }),
    win
  );
  assert.deepEqual(calls, ['restore', 'focus']);
  assert.equal(created, 0);
});

test('ensureMainWindowFocused creates the main window the user closed', () => {
  // On macOS the app keeps running with no window, so whatever has something to
  // show the user must be able to bring one back.
  const { ensureMainWindowFocused } = loadModule();
  const destroyed = createWindowState({ destroyed: true });
  let created = 0;

  // A created window is not returned: it has nothing loaded to send to yet.
  assert.equal(
    ensureMainWindowFocused({ getMainWindow: () => null, createMainWindow: () => created++ }),
    null
  );
  assert.equal(
    ensureMainWindowFocused({
      getMainWindow: () => destroyed.win,
      createMainWindow: () => created++,
    }),
    null
  );
  assert.equal(created, 2);
  assert.deepEqual(destroyed.calls, []);
});
