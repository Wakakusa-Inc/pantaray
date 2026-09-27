function createRetainedStringChannel({ ipcRenderer, channel, logError }) {
  let retainedValue = null;
  const subscribers = new Set();

  try {
    ipcRenderer.on(channel, (_event, value) => {
      retainedValue = typeof value === 'string' ? value : String(value ?? '');
      for (const subscriber of subscribers) {
        try {
          subscriber(retainedValue);
        } catch (error) {
          logError(`${channel} subscriber threw`, error);
        }
      }
    });
  } catch (error) {
    logError(`ipcRenderer.on(${channel}) failed`, error);
  }

  return {
    subscribe(callback) {
      subscribers.add(callback);
      if (retainedValue) {
        try {
          callback(retainedValue);
        } catch (error) {
          logError(`${channel} immediate delivery threw`, error);
        }
      }
      return () => subscribers.delete(callback);
    },
  };
}

function getSnapshotSuggestionId(payload, logError) {
  try {
    const snapshot = payload && typeof payload === 'object' ? payload.snapshot : null;
    const suggestionId =
      snapshot && typeof snapshot === 'object' && typeof snapshot.suggestionId === 'string'
        ? snapshot.suggestionId.trim()
        : '';
    return suggestionId || null;
  } catch (error) {
    logError('getSnapshotSuggestionId failed', error);
    return null;
  }
}

function createSnapshotChannel({ ipcRenderer, logError }) {
  const retainedBySuggestionId = new Map();
  const subscribers = new Set();

  try {
    ipcRenderer.on('overlay:snapshot', (_event, payload) => {
      const suggestionId = getSnapshotSuggestionId(payload, logError);
      if (!suggestionId) return;
      retainedBySuggestionId.set(suggestionId, payload);
      for (const subscriber of subscribers) {
        try {
          subscriber(payload);
        } catch (error) {
          logError('overlay:snapshot subscriber threw', error);
        }
      }
    });
  } catch (error) {
    logError('ipcRenderer.on(overlay:snapshot) failed', error);
  }

  return {
    subscribe(callback) {
      subscribers.add(callback);
      for (const payload of retainedBySuggestionId.values()) {
        try {
          callback(payload);
        } catch (error) {
          logError('overlay:snapshot immediate delivery threw', error);
        }
      }
      return () => subscribers.delete(callback);
    },
  };
}

function createOverlayApi({ ipcRenderer, ipcPolicy, logError }) {
  const { assertValidInvokeChannel, isValidSendChannel } = ipcPolicy;
  const contentChannel = createRetainedStringChannel({
    ipcRenderer,
    channel: 'set-content',
    logError,
  });
  const snapshotChannel = createSnapshotChannel({ ipcRenderer, logError });

  return {
    agentOverlay: {
      show: (content, options) => {
        if (!isValidSendChannel('show-notification')) return;
        const payload = options?.id ? { content, id: String(options.id) } : content;
        ipcRenderer.send('show-notification', payload);
      },
      showHistory: (payload) => {
        if (isValidSendChannel('history:openOverlay')) {
          ipcRenderer.send('history:openOverlay', payload);
        }
      },
      onSnapshot: snapshotChannel.subscribe,
      resize: (height, options) => {
        if (!isValidSendChannel('resize-notification-window')) return;
        const payload = options?.id ? { id: String(options.id), height } : height;
        ipcRenderer.send('resize-notification-window', payload);
      },
      onSetContent: contentChannel.subscribe,
      acceptAction: (data) => ipcRenderer.send('notification-action-accept', data),
      submitApprovalDecision: (payload) => {
        assertValidInvokeChannel('overlay:submitApprovalDecision');
        return ipcRenderer.invoke('overlay:submitApprovalDecision', payload);
      },
      getActionApprovalMode: (actionId) => {
        assertValidInvokeChannel('overlay:getActionApprovalMode');
        return ipcRenderer.invoke('overlay:getActionApprovalMode', actionId);
      },
      setActionApprovalMode: (payload) => {
        assertValidInvokeChannel('overlay:setActionApprovalMode');
        return ipcRenderer.invoke('overlay:setActionApprovalMode', payload);
      },
      dragStart: (payload) => {
        if (isValidSendChannel('overlay:dragStart')) {
          ipcRenderer.send('overlay:dragStart', payload);
        }
      },
      dragMove: (payload) => {
        if (isValidSendChannel('overlay:dragMove')) {
          ipcRenderer.send('overlay:dragMove', payload);
        }
      },
      dragEnd: () => {
        if (isValidSendChannel('overlay:dragEnd')) ipcRenderer.send('overlay:dragEnd');
      },
      openWorkspaceSettings: () => {
        if (isValidSendChannel('overlay:openWorkspaceSettings')) {
          ipcRenderer.send('overlay:openWorkspaceSettings');
        }
      },
      rejectAction: (data) => {
        if (isValidSendChannel('notification-action-reject')) {
          ipcRenderer.send('notification-action-reject', data);
        }
      },
      hide: () => {
        if (isValidSendChannel('notification-hide')) ipcRenderer.send('notification-hide');
      },
      stopAction: () => {
        if (isValidSendChannel('notification-stop-action')) {
          ipcRenderer.send('notification-stop-action');
        }
      },
    },
  };
}

module.exports = { createOverlayApi };
