const fs = require('fs');
const path = require('path');
const { LEVELS } = require('./log_levels');

/**
 * Release-time file sink for the Electron main-process logger.
 *
 * Policy:
 * - The packaged app keeps stdout silent; this sink records error-level (and
 *   above) already-redacted JSON lines to a writable, user-discoverable file
 *   under app.getPath('logs'), so a developer can ask the user to fetch it.
 * - No remote telemetry. Logging must never crash the app.
 *
 * The sink is module-level shared state so a single configureFileSink() call
 * affects every logger instance (loggers are created per-module at load time,
 * before the Electron app is ready).
 */

// 5 MiB per file: enough error history to debug, small enough to send/inspect.
const LOG_FILE_MAX_BYTES = 5 * 1024 * 1024;
// Keep the active file plus 4 rotated files (~25 MiB worst case on disk).
const LOG_FILE_MAX_FILES = 5;
// One JSON object per line; distinct name so it never collides with the Python
// local-backend log written into the same directory.
const ELECTRON_LOG_FILENAME = 'pantaray-main.jsonl';
// Records at this level (and above) are written to the file at release.
const FILE_SINK_LEVEL = 'error';

/**
 * @typedef {Object} FileSinkState
 * @property {string} filePath
 * @property {number} minLevelValue
 * @property {number} maxBytes
 * @property {number} maxFiles
 */

/** @type {FileSinkState | null} */
let state = null;

/**
 * Configure the shared file sink exactly once. Call this after the Electron app
 * is ready, when app.getPath('logs') is valid. Throws on invalid input or on a
 * second call so misconfiguration surfaces immediately. Filesystem setup is
 * best-effort: if the logs directory cannot be created, the sink stays disabled.
 *
 * @param {{ dir: string, level: string }} config
 */
function configureFileSink({ dir, level }) {
  if (state) {
    throw new Error('configureFileSink must be called exactly once.');
  }
  if (typeof dir !== 'string' || !dir.trim()) {
    throw new Error('configureFileSink requires a non-empty "dir".');
  }
  if (typeof level !== 'string' || !(level in LEVELS)) {
    throw new Error(`configureFileSink received an unknown level: ${String(level)}`);
  }
  const resolvedDir = path.resolve(dir);
  try {
    fs.mkdirSync(resolvedDir, { recursive: true });
  } catch {
    return;
  }
  state = {
    filePath: path.join(resolvedDir, ELECTRON_LOG_FILENAME),
    minLevelValue: LEVELS[level],
    maxBytes: LOG_FILE_MAX_BYTES,
    maxFiles: LOG_FILE_MAX_FILES,
  };
}

/**
 * Whether a record at `level` should be written to the file sink. Independent of
 * the stdout level so error records are captured even when stdout is silent.
 *
 * @param {string} level
 * @returns {boolean}
 */
function isFileSinkEnabledFor(level) {
  if (!state) return false;
  return (LEVELS[level] ?? 0) >= state.minLevelValue;
}

function currentFileSize(filePath) {
  try {
    return fs.statSync(filePath).size;
  } catch {
    return 0;
  }
}

/**
 * Rotate filePath -> filePath.1 -> ... -> filePath.(maxFiles-1), dropping the
 * oldest. Each step is guarded so a single fs error never aborts rotation.
 */
function rotate() {
  const { filePath, maxFiles } = state;
  const oldest = `${filePath}.${maxFiles - 1}`;
  try {
    if (fs.existsSync(oldest)) fs.rmSync(oldest);
  } catch {}
  for (let index = maxFiles - 2; index >= 1; index -= 1) {
    const from = `${filePath}.${index}`;
    const to = `${filePath}.${index + 1}`;
    try {
      if (fs.existsSync(from)) fs.renameSync(from, to);
    } catch {}
  }
  try {
    if (fs.existsSync(filePath)) fs.renameSync(filePath, `${filePath}.1`);
  } catch {}
}

/**
 * Append one already-serialized log line (including trailing newline), rotating
 * first if it would exceed the size cap.
 *
 * Logging is best-effort: a single intentional catch keeps a filesystem error
 * from crashing the app. We do NOT fall back to stdout — at release it is silent
 * by design.
 *
 * @param {string} line
 */
function appendLine(line) {
  if (!state) return;
  try {
    if (currentFileSize(state.filePath) + Buffer.byteLength(line) > state.maxBytes) {
      rotate();
    }
    fs.appendFileSync(state.filePath, line);
  } catch {
    // Intentional swallow: logging must never crash the app.
  }
}

/** Test-only: reset module state so each test can configure a fresh directory. */
function resetFileSinkForTests() {
  state = null;
}

module.exports = {
  LOG_FILE_MAX_BYTES,
  LOG_FILE_MAX_FILES,
  ELECTRON_LOG_FILENAME,
  FILE_SINK_LEVEL,
  configureFileSink,
  isFileSinkEnabledFor,
  appendLine,
  resetFileSinkForTests,
};
