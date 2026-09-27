const assert = require('node:assert/strict');
const test = require('node:test');

const { installOverlayInteractionRecorder } = require('../electron/preload_overlay_interaction');

function createWindowRef() {
  const listeners = new Map();
  return {
    addEventListener: (event, callback, options) => {
      listeners.set(event, { callback, options });
    },
    emit: (event) => {
      listeners.get(event)?.callback();
    },
    listeners,
  };
}

test('preload overlay interaction recorder sends pointerdown only from notification page', () => {
  const sends = [];
  const windowRef = createWindowRef();

  installOverlayInteractionRecorder({
    windowRef,
    ipcRenderer: {
      send: (channel) => sends.push(channel),
    },
    isNotificationHtmlWindow: () => true,
    isValidSendChannel: (channel) => channel === 'overlay:recordInteraction',
    logError: () => {},
  });

  windowRef.emit('pointerdown');

  assert.deepEqual(sends, ['overlay:recordInteraction']);
  assert.equal(windowRef.listeners.get('pointerdown').options.capture, true);
});

test('preload overlay interaction recorder is inert outside notification page', () => {
  const sends = [];
  const windowRef = createWindowRef();

  installOverlayInteractionRecorder({
    windowRef,
    ipcRenderer: {
      send: (channel) => sends.push(channel),
    },
    isNotificationHtmlWindow: () => false,
    isValidSendChannel: () => true,
    logError: () => {},
  });

  windowRef.emit('pointerdown');

  assert.deepEqual(sends, []);
  assert.equal(windowRef.listeners.size, 0);
});
