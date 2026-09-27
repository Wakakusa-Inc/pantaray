const WS_EVENT_BUFFER_MAX = 200;
const WS_EVENT_SEEN_MAX = 2000;

function isNotificationWindow(windowRef, logError) {
  try {
    return String(windowRef?.location?.pathname || '').endsWith('notification.html');
  } catch (error) {
    logError('isNotificationWindow failed', error);
    return false;
  }
}

function getEventId(payload) {
  if (!payload || typeof payload !== 'object' || !('event_id' in payload)) return null;
  const value = payload.event_id;
  if (value === null || value === undefined) return null;
  const normalized = String(value);
  return normalized || null;
}

function deduplicate(callback) {
  const seen = new Set();
  const order = [];
  return (payload) => {
    const eventId = getEventId(payload);
    if (eventId) {
      if (seen.has(eventId)) return;
      seen.add(eventId);
      order.push(eventId);
      if (order.length > WS_EVENT_SEEN_MAX) {
        seen.delete(order.shift());
      }
    }
    callback(payload);
  };
}

function createOrchestrationApi({ ipcRenderer, windowRef, logError }) {
  const overlaySubscribers = new Set();
  const overlayEventBuffer = [];
  const notificationWindow = isNotificationWindow(windowRef, logError);

  if (notificationWindow) {
    try {
      ipcRenderer.on('ws:event', (_event, payload) => {
        if (overlaySubscribers.size === 0) {
          overlayEventBuffer.push(payload);
          if (overlayEventBuffer.length > WS_EVENT_BUFFER_MAX) {
            overlayEventBuffer.shift();
          }
        }
        for (const subscriber of overlaySubscribers) {
          try {
            subscriber(payload);
          } catch (error) {
            logError('ws:event subscriber threw', error);
          }
        }
      });
    } catch (error) {
      logError('ipcRenderer.on(ws:event) failed', error);
    }
  }

  return {
    orchestration: {
      send: (message) => ipcRenderer.send('ws:send', message),
      acceptAction: (request) => ipcRenderer.invoke('ws:acceptAction', request),
      getStatus: () => ipcRenderer.invoke('ws:getStatus'),
      onEvent: (callback) => {
        if (notificationWindow) {
          const subscriber = deduplicate(callback);
          overlaySubscribers.add(subscriber);
          for (const payload of overlayEventBuffer.splice(0)) {
            try {
              subscriber(payload);
            } catch (error) {
              logError('ws:event subscriber threw during buffer flush', error);
            }
          }
          return () => overlaySubscribers.delete(subscriber);
        }
        const listener = (_event, payload) => callback(payload);
        ipcRenderer.on('ws:event', listener);
        return () => ipcRenderer.removeListener('ws:event', listener);
      },
      onStatus: (callback) => {
        const listener = (_event, payload) => callback(payload);
        ipcRenderer.on('ws:status', listener);
        return () => ipcRenderer.removeListener('ws:status', listener);
      },
    },
  };
}

module.exports = { createOrchestrationApi, isNotificationWindow };
