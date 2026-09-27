const assert = require('node:assert/strict');
const { test } = require('node:test');

const { presentRecordingIntro } = require('../electron/dist/windows/recordingIntroWindow.js');

function createMainWindow(overrides = {}) {
  const state = { destroyed: false, minimized: false, visible: true, ...overrides };
  const sent = [];
  return {
    sent,
    win: {
      isDestroyed: () => state.destroyed,
      isMinimized: () => state.minimized,
      restore: () => {
        state.minimized = false;
      },
      isVisible: () => state.visible,
      show: () => {
        state.visible = true;
      },
      focus: () => undefined,
      webContents: { send: (...args) => sent.push(args) },
    },
  };
}

test('the recording screen is asked for again in the window already in front', () => {
  // `focus()` on the frontmost window fires no focus event, so the renderer would
  // never re-read the gate that opens the screen.
  const { sent, win } = createMainWindow();
  let created = 0;

  presentRecordingIntro({ getMainWindow: () => win, createMainWindow: () => created++ });

  assert.equal(created, 0);
  assert.deepEqual(sent, [['recording:gateStateChanged']]);
});

test('a main window created for the recording screen is not sent to', () => {
  // It reads the gate as it mounts, and there is no renderer to send to yet.
  const destroyed = createMainWindow({ destroyed: true });
  let created = 0;

  presentRecordingIntro({ getMainWindow: () => null, createMainWindow: () => created++ });
  presentRecordingIntro({ getMainWindow: () => destroyed.win, createMainWindow: () => created++ });

  assert.equal(created, 2);
  assert.deepEqual(destroyed.sent, []);
});
