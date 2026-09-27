function parseDragPoint(payload) {
  if (!payload || typeof payload !== 'object') return null;
  const screenX = Number(payload.screenX);
  const screenY = Number(payload.screenY);
  if (!Number.isFinite(screenX) || !Number.isFinite(screenY)) return null;
  return { screenX, screenY };
}

function normalizeBounds(bounds) {
  if (!bounds || typeof bounds !== 'object') return null;
  const x = Number(bounds.x);
  const y = Number(bounds.y);
  const width = Number(bounds.width);
  const height = Number(bounds.height);
  if (![x, y, width, height].every(Number.isFinite)) return null;
  return { x, y, width, height };
}

function normalizeWorkArea(display) {
  const workArea = display && display.workArea;
  if (!workArea || typeof workArea !== 'object') return null;
  const x = Number(workArea.x);
  const y = Number(workArea.y);
  const width = Number(workArea.width);
  const height = Number(workArea.height);
  if (![x, y, width, height].every(Number.isFinite)) return null;
  return { x, y, width, height };
}

function clampPosition(screen, bounds, nextX, nextY) {
  const currentBounds = normalizeBounds(bounds);
  if (!currentBounds || !Number.isFinite(nextX) || !Number.isFinite(nextY)) return null;
  const targetBounds = { ...currentBounds, x: nextX, y: nextY };
  const display = screen.getDisplayMatching(targetBounds) || screen.getPrimaryDisplay();
  const workArea = normalizeWorkArea(display) || normalizeWorkArea(screen.getPrimaryDisplay());
  if (!workArea) return null;
  const minX = workArea.x;
  const minY = workArea.y;
  const maxX = workArea.x + workArea.width - currentBounds.width;
  const maxY = workArea.y + workArea.height - currentBounds.height;
  const x = Math.max(minX, Math.min(nextX, Math.max(minX, maxX)));
  const y = Math.max(minY, Math.min(nextY, Math.max(minY, maxY)));
  if (!Number.isFinite(x) || !Number.isFinite(y)) return null;
  return {
    x: Math.round(x),
    y: Math.round(y),
  };
}

function createOverlayDragController(params) {
  const { BrowserWindow, screen, activationTracker } = params;
  const sessions = new Map();

  function getOverlayFromEvent(event) {
    try {
      const sender = event && event.sender;
      const win = sender ? BrowserWindow.fromWebContents(sender) : null;
      if (!activationTracker.isOverlayWindow(win)) return null;
      return { sender, win };
    } catch {
      return null;
    }
  }

  function end(sender) {
    if (!sender || !sessions.has(sender)) return;
    sessions.delete(sender);
    activationTracker.endInteraction();
  }

  return {
    clearForWindow(win) {
      for (const [sender, session] of [...sessions.entries()]) {
        if (session.win === win) {
          end(sender);
        }
      }
    },
    start(event, payload) {
      const point = parseDragPoint(payload);
      const overlay = getOverlayFromEvent(event);
      if (!point || !overlay || !overlay.sender || overlay.win.isDestroyed()) return;
      const startBounds = normalizeBounds(overlay.win.getBounds());
      if (!startBounds) return;
      end(overlay.sender);
      sessions.set(overlay.sender, {
        win: overlay.win,
        startPoint: point,
        startBounds,
      });
      activationTracker.beginInteraction();
    },
    move(event, payload) {
      const point = parseDragPoint(payload);
      const sender = event && event.sender;
      const session = sender ? sessions.get(sender) : null;
      if (!point || !session || !session.startBounds || !session.win || session.win.isDestroyed()) {
        return;
      }
      const nextX = session.startBounds.x + (point.screenX - session.startPoint.screenX);
      const nextY = session.startBounds.y + (point.screenY - session.startPoint.screenY);
      const nextPosition = clampPosition(screen, session.win.getBounds(), nextX, nextY);
      if (!nextPosition) return;
      if (typeof session.win.setPosition === 'function') {
        try {
          session.win.setPosition(nextPosition.x, nextPosition.y);
        } catch {
          end(sender);
        }
      }
    },
    end(event) {
      end(event && event.sender);
    },
  };
}

module.exports = {
  createOverlayDragController,
};
