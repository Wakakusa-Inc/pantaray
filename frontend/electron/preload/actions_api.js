function createActionsApi({ ipcRenderer }) {
  // The main window receives every Action's updates and the History list needs each running one,
  // so a late subscriber gets the latest update of every Action, not only the last to change.
  // Design limit: one snapshot per Action updated since the last reset; drop terminal entries if
  // the main window's memory grows measurably over a long session.
  const latestUpdates = new Map();
  let pendingReset = false;
  const subscribers = new Set();

  ipcRenderer.on('action:conversationUpdated', (_event, update) => {
    if (update?.kind === 'reset') {
      latestUpdates.clear();
      pendingReset = subscribers.size === 0;
    } else if (update?.kind === 'action_updated' && update.snapshot?.actionId) {
      latestUpdates.delete(update.snapshot.actionId);
      latestUpdates.set(update.snapshot.actionId, update);
    } else {
      return;
    }
    subscribers.forEach((subscriber) => subscriber(update));
  });

  return {
    actions: {
      submitMessage: (request) => ipcRenderer.invoke('action:submitMessage', request),
      resumeAction: (request) => ipcRenderer.invoke('action:resume', request),
      attachImage: (request) => ipcRenderer.invoke('action:attachImage', request),
      revealImage: (request) => ipcRenderer.invoke('actionImage:reveal', request),
      attachFile: (request) => ipcRenderer.invoke('action:attachFile', request),
      discardAttachment: (request) => ipcRenderer.invoke('action:discardAttachment', request),
      readConversationPage: (request) => ipcRenderer.invoke('action:readConversationPage', request),
      readToolOutputPage: (request) => ipcRenderer.invoke('action:readToolOutputPage', request),
      onConversationUpdated: (callback) => {
        subscribers.add(callback);
        if (pendingReset) {
          pendingReset = false;
          callback({ kind: 'reset' });
        }
        latestUpdates.forEach((update) => callback(update));
        return () => subscribers.delete(callback);
      },
    },
  };
}

module.exports = { createActionsApi };
