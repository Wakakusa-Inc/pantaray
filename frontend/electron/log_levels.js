const LEVELS = /** @type {const} */ ({
  debug: 10,
  info: 20,
  warn: 30,
  error: 40,
  silent: 1000,
});

function normalizeLevel(value) {
  const raw = String(value || '').toLowerCase().trim();
  if (raw in LEVELS) return raw;
  return 'info';
}

/**
 * Shared log-level definitions for the Electron main-process logger and its
 * file sink. Kept in a dedicated module so both can import a single source of
 * truth without creating a circular dependency between logger.js and
 * log_file_sink.js.
 */
module.exports = {
  LEVELS,
  normalizeLevel,
};
