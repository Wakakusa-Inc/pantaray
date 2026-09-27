const assert = require('assert');
const { test } = require('node:test');

const { wireMainIpcRuntime } = require('../electron/dist/main_runtime/ipcBootstrap.js');

test('main IPC bootstrap configures auxiliary window security before registering handlers', () => {
  const calls = [];
  const context = { security: { authorize: () => 'main' } };
  const dispose = () => {};

  const runtime = wireMainIpcRuntime({
    context,
    notificationWindow: {
      configureIpcWindowSecurity: (security) => calls.push(['security', security]),
    },
    registerHandlers: (receivedContext) => {
      calls.push(['handlers', receivedContext]);
      return { registered: { invoke: [], send: [] }, dispose };
    },
  });

  assert.deepEqual(calls, [
    ['security', context.security],
    ['handlers', context],
  ]);
  assert.equal(runtime.context, context);
  assert.equal(runtime.dispose, dispose);
});
