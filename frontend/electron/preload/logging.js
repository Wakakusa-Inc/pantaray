const PRELOAD_LOG_INTERVAL_MS = 1500;

function createPreloadLogger({ processRef, consoleRef, now = Date.now }) {
  const isDevelopment = String(processRef.env.NODE_ENV || '').toLowerCase() === 'development';
  const lastLoggedAt = new Map();

  function logError(label, error, options = {}) {
    if (!isDevelopment) return;
    const intervalMs = Number.isFinite(options.intervalMs)
      ? Math.max(0, Number(options.intervalMs))
      : PRELOAD_LOG_INTERVAL_MS;
    const timestamp = now();
    const previousTimestamp = lastLoggedAt.get(label) || 0;
    if (intervalMs > 0 && timestamp - previousTimestamp < intervalMs) return;
    lastLoggedAt.set(label, timestamp);
    consoleRef.error(`[preload] ${label}`, error);
  }

  function disableReleaseConsole() {
    const packaged = String(processRef.env.PANTARAY_PACKAGED || '')
      .trim()
      .toLowerCase();
    if (packaged !== '1' && packaged !== 'true') return;
    const noop = () => {};
    for (const method of ['log', 'info', 'warn', 'error', 'debug', 'trace']) {
      if (typeof consoleRef[method] === 'function') consoleRef[method] = noop;
    }
  }

  return { disableReleaseConsole, logError };
}

module.exports = { createPreloadLogger };
