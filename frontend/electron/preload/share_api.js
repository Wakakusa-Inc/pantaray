function createShareApi({ ipcRenderer }) {
  return {
    share: {
      savePng: (payload) => ipcRenderer.invoke('share:savePng', payload),
      captureShareCard: (payload) => ipcRenderer.invoke('share:captureShareCard', payload),
    },
  };
}

module.exports = { createShareApi };
