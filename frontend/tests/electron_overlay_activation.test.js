const assert = require('node:assert/strict');
const test = require('node:test');
const fs = require('node:fs');
const ts = require('typescript');

function loadModule() {
  const sourcePath = require.resolve('../electron/src/windows/overlayActivation.ts');
  const source = fs.readFileSync(sourcePath, 'utf8');
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

function createHarness({ overOverlay, recentInteraction }) {
  const timers = [];
  const restoreCalls = [];
  const overlayPointCalls = [];
  const interactionReferenceCalls = [];
  const { createOverlayAwareActivateHandler } = loadModule();
  const handler = createOverlayAwareActivateHandler({
    overlay: {
      isVisibleOverlayAtPoint: (point) => {
        overlayPointCalls.push(point);
        return overOverlay;
      },
      hasRecentOverlayInteraction: (referenceMs) => {
        interactionReferenceCalls.push(referenceMs);
        return recentInteraction();
      },
    },
    screen: {
      getCursorScreenPoint: () => ({ x: 10, y: 20 }),
    },
    now: () => 1000,
    setTimer: (callback, delayMs) => {
      timers.push({ callback, delayMs });
      return timers.length;
    },
    clearTimer: () => {},
    interactionWaitMs: 80,
  });
  return {
    handler,
    timers,
    restoreCalls,
    overlayPointCalls,
    interactionReferenceCalls,
    restore: () => restoreCalls.push('restore'),
  };
}

test('overlay activate restores immediately when the cursor is not over an overlay', () => {
  const harness = createHarness({
    overOverlay: false,
    recentInteraction: () => false,
  });

  harness.handler.handleActivate(harness.restore);

  assert.deepEqual(harness.restoreCalls, ['restore']);
  assert.equal(harness.timers.length, 0);
  assert.deepEqual(harness.overlayPointCalls, [{ x: 10, y: 20 }]);
});

test('overlay activate suppresses restore after a recent interaction even when the overlay is already hidden', () => {
  const harness = createHarness({
    overOverlay: false,
    recentInteraction: () => true,
  });

  harness.handler.handleActivate(harness.restore);

  assert.deepEqual(harness.restoreCalls, []);
  assert.equal(harness.timers.length, 0);
  assert.deepEqual(harness.overlayPointCalls, []);
});

test('overlay activate defers and restores when no overlay interaction arrives', () => {
  const harness = createHarness({
    overOverlay: true,
    recentInteraction: () => false,
  });

  harness.handler.handleActivate(harness.restore);

  assert.deepEqual(harness.restoreCalls, []);
  assert.equal(harness.timers.length, 1);
  assert.equal(harness.timers[0].delayMs, 80);

  harness.timers[0].callback();

  assert.deepEqual(harness.restoreCalls, ['restore']);
  assert.deepEqual(harness.interactionReferenceCalls, [1000, 1000]);
});

test('overlay activate suppresses restore when an overlay interaction is already recent', () => {
  const harness = createHarness({
    overOverlay: true,
    recentInteraction: () => true,
  });

  harness.handler.handleActivate(harness.restore);

  assert.deepEqual(harness.restoreCalls, []);
  assert.equal(harness.timers.length, 0);
});

test('overlay activate suppresses delayed restore when interaction arrives during the wait', () => {
  let recent = false;
  const harness = createHarness({
    overOverlay: true,
    recentInteraction: () => recent,
  });

  harness.handler.handleActivate(harness.restore);
  recent = true;
  harness.timers[0].callback();

  assert.deepEqual(harness.restoreCalls, []);
});
