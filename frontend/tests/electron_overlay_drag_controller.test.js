const assert = require('node:assert/strict');
const test = require('node:test');

const { createOverlayDragController } = require('../electron/overlay_drag_controller');

function createControllerHarness(options = {}) {
  const webContents = {};
  const bounds = options.bounds || { x: 10, y: 20, width: 100, height: 80 };
  const positions = [];
  const win = {
    isDestroyed: () => false,
    getBounds: () => ({ ...bounds }),
    setPosition: (x, y) => {
      positions.push({ x, y });
    },
  };
  const activationTracker = {
    isOverlayWindow: (candidate) => candidate === win,
    beginInteraction: () => {},
    endInteraction: () => {},
  };
  const controller = createOverlayDragController({
    BrowserWindow: {
      fromWebContents: (candidate) => (candidate === webContents ? win : null),
    },
    screen: {
      getDisplayMatching: () => options.display || { workArea: { x: 0, y: 0, width: 500, height: 400 } },
      getPrimaryDisplay: () => ({ workArea: { x: 0, y: 0, width: 500, height: 400 } }),
    },
    activationTracker,
  });

  return { controller, webContents, positions };
}

test('overlay drag controller rounds finite positions before setPosition', () => {
  const { controller, webContents, positions } = createControllerHarness();

  controller.start({ sender: webContents }, { screenX: 100.2, screenY: 50.2 });
  controller.move({ sender: webContents }, { screenX: 115.8, screenY: 64.7 });

  assert.deepEqual(positions, [{ x: 26, y: 35 }]);
});

test('overlay drag controller skips setPosition when bounds are invalid', () => {
  const { controller, webContents, positions } = createControllerHarness({
    bounds: { x: 10, y: undefined, width: 100, height: 80 },
  });

  controller.start({ sender: webContents }, { screenX: 100, screenY: 50 });
  controller.move({ sender: webContents }, { screenX: 120, screenY: 70 });

  assert.deepEqual(positions, []);
});
