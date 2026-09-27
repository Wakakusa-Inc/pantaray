const fs = require('fs');
const path = require('path');
const { randomBytes } = require('crypto');

const LOG_SALT_FILENAME = 'log-salt';
// 32 bytes (256-bit) random salt: enough entropy to keep fingerprints
// non-reversible via brute force / rainbow tables.
const LOG_SALT_BYTES = 32;

/**
 * Resolve the log salt used by the logger's fingerprint().
 *
 * Packaged builds do not trust .env, so PANTARAY_LOG_SALT may be unset there.
 * Without a salt, fingerprint() throws and release error logs lose their detail
 * — exactly when file logging is meant to help. To keep logging functional while
 * preserving fingerprint un-reversibility, persist a machine-specific random
 * salt under userDataDir on first use.
 *
 * Returns the existing env salt if set; otherwise the persisted (or freshly
 * generated) salt. The caller assigns the result to process.env.PANTARAY_LOG_SALT.
 *
 * @param {string} userDataDir
 * @returns {string}
 */
function ensureLogSalt(userDataDir) {
  const existing = String(process.env.PANTARAY_LOG_SALT || '').trim();
  if (existing) return existing;

  const saltPath = path.join(userDataDir, LOG_SALT_FILENAME);
  let salt = '';
  try {
    salt = fs.readFileSync(saltPath, 'utf8').trim();
  } catch {
    // Not generated yet.
  }
  if (salt) return salt;

  salt = randomBytes(LOG_SALT_BYTES).toString('hex');
  try {
    fs.mkdirSync(path.dirname(saltPath), { recursive: true });
    fs.writeFileSync(saltPath, salt, { mode: 0o600 });
  } catch {
    // Persistence failed; use the in-memory salt so fingerprinting still works
    // for this process. Logging must remain functional.
  }
  return salt;
}

module.exports = { ensureLogSalt, LOG_SALT_FILENAME };
