const assert = require('assert');
const { test } = require('node:test');

// NOTE:
// - share:savePng は「Downloadsへ固定保存」するためのIPC。
// - ここでは Electron 実体に依存しない範囲で、入力検証が fail-closed であることを回帰固定する。

const { registerShareHandlers } = require('../electron/dist/ipc/handlers/share.js');

function createFakeRegistrar() {
  /** @type {Map<string, Function>} */
  const invokeHandlers = new Map();
  return {
    invokeHandlers,
    handle: (channel, handler) => {
      invokeHandlers.set(channel, handler);
    },
  };
}

test('share:savePng rejects invalid filename (path traversal)', async () => {
  const registrar = createFakeRegistrar();
  registerShareHandlers({}, registrar);
  const handler = registrar.invokeHandlers.get('share:savePng');
  assert.equal(typeof handler, 'function');

  const res = await handler({}, { filename: '../evil.png', pngBytes: [0, 1, 2] });
  assert.deepEqual(res, { ok: false, error: 'Invalid filename.' });
});

test('share:savePng rejects uppercase extension (strict)', async () => {
  const registrar = createFakeRegistrar();
  registerShareHandlers({}, registrar);
  const handler = registrar.invokeHandlers.get('share:savePng');

  const res = await handler({}, { filename: 'pantaray-20260107-123456-123.PNG', pngBytes: [0, 1, 2] });
  assert.deepEqual(res, { ok: false, error: 'Invalid filename.' });
});

test('share:savePng accepts filename format and fails closed on non-PNG signature', async () => {
  const registrar = createFakeRegistrar();
  registerShareHandlers({}, registrar);
  const handler = registrar.invokeHandlers.get('share:savePng');

  const res = await handler({}, { filename: 'pantaray-20260107-123456-123.png', pngBytes: [0, 1, 2, 3] });
  assert.deepEqual(res, { ok: false, error: 'Invalid PNG signature.' });
});


