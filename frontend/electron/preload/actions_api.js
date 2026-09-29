function createActionsApi({ ipcRenderer }) {
  let latestUpdate = null;
  let pendingReset = false;
  const subscribers = new Set();

  ipcRenderer.on('action:conversationUpdated', (_event, update) => {
    if (update?.kind === 'reset') {
      latestUpdate = null;
      pendingReset = subscribers.size === 0;
    } else if (update?.kind === 'action_updated' && update.snapshot?.actionId) {
      latestUpdate = update;
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
        if (latestUpdate) callback(latestUpdate);
        return () => subscribers.delete(callback);
      },
    },
  };
}

module.exports = { createActionsApi };
