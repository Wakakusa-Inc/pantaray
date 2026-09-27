const assert = require('assert');
const { test } = require('node:test');

const { createAuxiliaryWindowIpcSecurity } = require('../electron/auxiliary_window_ipc_security');

function createFakeWindow(sender = { id: 1 }) {
  const listeners = new Map();
  return {
    webContents: sender,
    once(event, listener) {
      listeners.set(event, listener);
    },
    emit(event) {
      listeners.get(event)?.();
    },
  };
}

test('auxiliary window IPC security registers and unregisters the same sender', () => {
  const calls = [];
  const security = createAuxiliaryWindowIpcSecurity();
  security.configure({
    registerWindow: (role, sender) => calls.push(['register', role, sender]),
    unregisterWindow: (sender) => calls.push(['unregister', sender]),
  });
  const sender = { id: 42 };
  const win = createFakeWindow(sender);

  security.registerWindow('overlay', win);
  win.emit('closed');

  assert.deepEqual(calls, [
    ['register', 'overlay', sender],
    ['unregister', sender],
  ]);
});

test('auxiliary window IPC security fails closed before configuration', () => {
  const security = createAuxiliaryWindowIpcSecurity();
  assert.throws(() => security.registerWindow('overlay', createFakeWindow()), /is not configured/);
});
