const assert = require('assert');
const Module = require('node:module');
const { test } = require('node:test');

const shareCard = require('../electron/dist/ipc/handlers/shareCard.js');

test('sharecard: normalizeCapturePayload rejects invalid payloads', () => {
  const { normalizeCapturePayload } = shareCard.__test__;

  assert.equal(normalizeCapturePayload(null), null);
  assert.equal(normalizeCapturePayload('x'), null);
  assert.equal(
    normalizeCapturePayload({
      // missing required keys
      suggestionText: 'a',
    }),
    null
  );

  assert.equal(
    normalizeCapturePayload({
      content: null,
      suggestionText: 'a',
      isSuggestionStreamFinished: true,
      isSuggestionAccepted: false,
      suggestionReaction: null,
      terminalStatusLabel: null,
      actionText: '',
      isActionStreamFinished: true,
      isActionPhase: false,
    }) != null,
    true
  );
});

test('sharecard: the IPC payload preserves explicit approval and rejects an invalid flag', () => {
  const { normalizeCapturePayload } = shareCard.__test__;
  const payload = {
    content: null,
    suggestionText: 'Approved proposal',
    isSuggestionStreamFinished: true,
    isSuggestionAccepted: true,
    actionText: 'Result',
    isActionStreamFinished: true,
    isActionPhase: true,
  };
  assert.deepEqual(normalizeCapturePayload(payload), payload);
  assert.equal(normalizeCapturePayload({ ...payload, isSuggestionAccepted: 'true' }), null);
});

test('sharecard: computeResize enforces width=1600', () => {
  const { computeResize } = shareCard.__test__;

  // 3200x2000 -> 1600x1000
  assert.deepEqual(computeResize({ width: 3200, height: 2000 }), { width: 1600, height: 1000 });

  // 1600x20000 -> height is preserved (no height cap)
  assert.deepEqual(computeResize({ width: 1600, height: 20000 }), { width: 1600, height: 20000 });

  // 800x5000 -> 1600x10000 (width scaling doubles height)
  assert.deepEqual(computeResize({ width: 800, height: 5000 }), { width: 1600, height: 10000 });
});

test('sharecard: computeCaptureWindowHeight clamps measured height', () => {
  const { computeCaptureWindowHeight } = shareCard.__test__;

  assert.equal(computeCaptureWindowHeight(1000), 1000);
  assert.equal(computeCaptureWindowHeight(100), 120);
});

test('sharecard: computeShareCardCapturePlan splits long cards into viewport segments', () => {
  const { computeShareCardCapturePlan } = shareCard.__test__;

  assert.deepEqual(computeShareCardCapturePlan(1000), {
    totalHeight: 1000,
    viewportHeight: 1000,
    segments: [{ offset: 0, visibleHeight: 1000 }],
  });

  assert.deepEqual(computeShareCardCapturePlan(2500), {
    totalHeight: 2500,
    viewportHeight: 1200,
    segments: [
      { offset: 0, visibleHeight: 1200 },
      { offset: 1200, visibleHeight: 1200 },
      { offset: 2400, visibleHeight: 100 },
    ],
  });
});

test('sharecard: formatShareTimestamp includes milliseconds', () => {
  const { formatShareTimestamp } = shareCard.__test__;
  const d = new Date('2020-01-02T03:04:05.006Z');
  // NOTE: local time zone affects hour/min/sec. Here we only validate shape.
  const s = formatShareTimestamp(d);
  assert.ok(/^20[0-9]{2}[0-9]{2}[0-9]{2}-[0-9]{6}-[0-9]{3}$/.test(s));
});

test('sharecard: unregisters the registered sender after window destruction', async () => {
  const sender = { id: 42 };
  let destroyed = false;
  class FakeBrowserWindow {
    get webContents() {
      if (destroyed) throw new Error('webContents accessed after destruction');
      return sender;
    }

    async loadFile() {
      destroyed = true;
      throw new Error('window disposed during load');
    }

    isDestroyed() {
      return destroyed;
    }
  }
  const electron = {
    app: { isPackaged: true, getPath: () => '/tmp' },
    BrowserWindow: FakeBrowserWindow,
  };
  const originalLoad = Module._load;
  Module._load = function patchedLoad(request, parent, isMain) {
    if (request === 'electron') return electron;
    return originalLoad.call(this, request, parent, isMain);
  };
  const registered = [];
  const unregistered = [];
  const handlers = new Map();
  const ctx = {
    security: {
      registerWindow: (_role, value) => registered.push(value),
      unregisterWindow: (value) => unregistered.push(value),
    },
  };
  shareCard.registerShareCardHandlers(ctx, {
    on: () => {},
    handle: (channel, handler) => handlers.set(channel, handler),
  });
  const handler = handlers.get('share:captureShareCard');
  assert.equal(typeof handler, 'function');

  try {
    const result = await handler({}, {
      content: null,
      suggestionText: 'suggestion',
      isSuggestionStreamFinished: true,
      isSuggestionAccepted: false,
      actionText: '',
      isActionStreamFinished: true,
      isActionPhase: false,
    });
    assert.deepEqual(result, { ok: false, error: 'window disposed during load' });
  } finally {
    Module._load = originalLoad;
  }

  assert.deepEqual(registered, [sender]);
  assert.deepEqual(unregistered, [sender]);
});
