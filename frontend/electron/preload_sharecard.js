// Minimal preload for sharecard capture window.
// Purpose: Reduce attack surface vs the full preload.js (no invoke APIs exposed).
const { contextBridge, ipcRenderer } = require('electron');

// ---- Overlay content delivery (race-free) ----
let lastSetContent = null;
const setContentSubscribers = new Set();

try {
  ipcRenderer.on('set-content', (_evt, content) => {
    lastSetContent = typeof content === 'string' ? content : String(content ?? '');
    try {
      for (const cb of setContentSubscribers) {
        try { cb(lastSetContent); } catch {}
      }
    } catch {}
  });
} catch {
  // no-op
}

contextBridge.exposeInMainWorld('electron', {
  ipcRenderer: {
    // Sharecard only needs to send readiness.
    send: (channel, ...args) => {
      if (channel === 'sharecard:ready') {
        ipcRenderer.send(channel, ...args);
      }
    },
  },
  agentOverlay: {
    onSetContent: (callback) => {
      const cb = (content) => callback(content);
      setContentSubscribers.add(cb);
      if (typeof lastSetContent === 'string' && lastSetContent.length > 0) {
        try { cb(lastSetContent); } catch {}
      }
      return () => {
        try { setContentSubscribers.delete(cb); } catch {}
      };
    },
  },
});


