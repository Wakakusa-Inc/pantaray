function createCoreApi({ ipcRenderer, ipcPolicy, initialUiLanguage, processRef }) {
  const { assertValidInvokeChannel, isValidReceiveChannel, isValidSendChannel } = ipcPolicy;

  return {
    ipcRenderer: {
      invoke: (channel, ...args) => {
        assertValidInvokeChannel(channel);
        return ipcRenderer.invoke(channel, ...args);
      },
      send: (channel, ...args) => {
        if (isValidSendChannel(channel)) {
          ipcRenderer.send(channel, ...args);
        }
      },
      on: (channel, callback) => {
        if (!isValidReceiveChannel(channel)) return () => {};
        const listener = (_event, ...args) => callback(...args);
        ipcRenderer.on(channel, listener);
        return () => ipcRenderer.removeListener(channel, listener);
      },
    },
    window: {
      getPosition: () => ipcRenderer.invoke('window:getPosition'),
      move: (position) => {
        if (typeof position?.x === 'number' && typeof position?.y === 'number') {
          void ipcRenderer.invoke('window:move', position);
        }
      },
      close: () => ipcRenderer.invoke('window:close'),
    },
    process: {
      platform: processRef.platform,
      env: { NODE_ENV: processRef.env.NODE_ENV },
    },
    ui: {
      initialLanguage: initialUiLanguage,
      getLanguage: () => ipcRenderer.invoke('ui:getLanguage'),
      setLanguage: (language) => ipcRenderer.invoke('ui:setLanguage', language),
      onLanguageChanged: (callback) => {
        if (!isValidReceiveChannel('ui:languageChanged')) return () => {};
        const listener = (_event, payload) => callback(payload);
        ipcRenderer.on('ui:languageChanged', listener);
        return () => ipcRenderer.removeListener('ui:languageChanged', listener);
      },
    },
    update: {
      getReadyNotice: () => ipcRenderer.invoke('update:getReadyNotice'),
      dismissReadyNotice: () => ipcRenderer.invoke('update:dismissReadyNotice'),
      restartToUpdate: () => ipcRenderer.invoke('update:restartToUpdate'),
      onReadyNoticeChanged: (callback) => {
        const listener = () => callback();
        ipcRenderer.on('update:readyNoticeChanged', listener);
        return () => ipcRenderer.removeListener('update:readyNoticeChanged', listener);
      },
    },
  };
}

module.exports = { createCoreApi };
