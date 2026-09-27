/**
 * AuthAttemptStore
 *
 * Desktop(main) が生成する PKCE attempt を短時間だけ保持する。
 *
 * 目的:
 * - deep link へ token を載せない（exchange_code 方式）
 * - code_verifier は秘密なので renderer に渡さず、main のみが保持する
 * - アプリがフォアグラウンド復帰するまでの間（数分）に deep link が戻るケースに備え、
 *   safeStorage で暗号化して userData へ短期保存する（TTL）
 */

const fs = require('fs');
const path = require('path');

/**
 * @param {unknown} safeStorage
 * @returns {safeStorage is { isEncryptionAvailable: () => boolean, encryptString: (s: string) => Buffer, decryptString: (b: Buffer) => string }}
 */
function isElectronSafeStorage(safeStorage) {
  return (
    !!safeStorage &&
    typeof safeStorage === 'object' &&
    typeof safeStorage.isEncryptionAvailable === 'function' &&
    typeof safeStorage.encryptString === 'function' &&
    typeof safeStorage.decryptString === 'function'
  );
}

class AuthAttemptStore {
  /**
   * @param {Object} options
   * @param {string} options.userDataDir
   * @param {unknown} options.safeStorage
   * @param {number} [options.ttlMs] - attempt の有効期限（ミリ秒）
   * @param {{ info?: Function, warn?: Function, error?: Function, debug?: Function }} [options.logger]
   */
  constructor(options) {
    this._userDataDir = String(options.userDataDir || '').trim();
    this._safeStorage = options.safeStorage;
    this._ttlMs = Number(options.ttlMs || 10 * 60 * 1000); // default 10min
    this._logger = options.logger || console;
    this._storagePath = path.join(this._userDataDir, 'auth-attempts.enc.json');
    /** @type {Map<string, { verifier: string, createdAt: number }>} */
    this._mem = new Map();

    this._loadFromDisk();
    this._prune();
  }

  /**
   * @returns {boolean}
   */
  _canEncrypt() {
    if (!isElectronSafeStorage(this._safeStorage)) return false;
    try {
      return Boolean(this._safeStorage.isEncryptionAvailable());
    } catch {
      return false;
    }
  }

  /**
   * @private
   */
  _loadFromDisk() {
    try {
      if (!this._canEncrypt()) return;
      if (!fs.existsSync(this._storagePath)) return;
      const raw = fs.readFileSync(this._storagePath, 'utf8');
      const parsed = JSON.parse(raw);
      const b64 = parsed?.ciphertext_b64;
      if (!b64 || typeof b64 !== 'string') return;
      const plain = this._safeStorage.decryptString(Buffer.from(b64, 'base64'));
      const obj = JSON.parse(plain);
      const items = obj?.items;
      if (!items || typeof items !== 'object') return;
      for (const [attemptId, value] of Object.entries(items)) {
        const v = value && typeof value === 'object' ? value : null;
        const verifier = v && typeof v.verifier === 'string' ? v.verifier : '';
        const createdAt = v && typeof v.createdAt === 'number' ? v.createdAt : 0;
        if (attemptId && verifier && createdAt > 0) {
          this._mem.set(String(attemptId), { verifier, createdAt });
        }
      }
    } catch (e) {
      this._logger.warn?.('AuthAttemptStore: load failed:', e);
    }
  }

  /**
   * @private
   */
  _saveToDisk() {
    try {
      if (!this._canEncrypt()) return;
      const items = {};
      for (const [k, v] of this._mem.entries()) {
        items[k] = { verifier: v.verifier, createdAt: v.createdAt };
      }
      const plain = JSON.stringify({ v: 1, items }, null, 0);
      const buf = this._safeStorage.encryptString(plain);
      const ciphertext_b64 = Buffer.isBuffer(buf) ? buf.toString('base64') : '';
      if (!ciphertext_b64) return;
      fs.writeFileSync(
        this._storagePath,
        JSON.stringify({ v: 1, ciphertext_b64 }, null, 2),
        { encoding: 'utf8', mode: 0o600 }
      );
    } catch (e) {
      this._logger.warn?.('AuthAttemptStore: save failed:', e);
    }
  }

  /**
   * @private
   */
  _prune() {
    const now = Date.now();
    let changed = false;
    for (const [k, v] of this._mem.entries()) {
      if (!v || typeof v.createdAt !== 'number' || now - v.createdAt > this._ttlMs) {
        this._mem.delete(k);
        changed = true;
      }
    }
    if (changed) this._saveToDisk();
  }

  /**
   * attempt を追加する。
   * @param {string} attemptId
   * @param {string} verifier
   */
  put(attemptId, verifier) {
    if (!attemptId || !verifier) return;
    this._prune();
    this._mem.set(String(attemptId), { verifier: String(verifier), createdAt: Date.now() });
    this._saveToDisk();
  }

  /**
   * attempt を取得する（削除しない）。
   * - 自己回復のポーリング等で「成功した時だけ consume」したいケース向け。
   * @param {string} attemptId
   * @returns {string | null} verifier
   */
  get(attemptId) {
    if (!attemptId) return null;
    this._prune();
    const v = this._mem.get(String(attemptId));
    return v ? v.verifier || null : null;
  }

  /**
   * attempt を取得して削除する（ワンタイム）。
   * @param {string} attemptId
   * @returns {string | null} verifier
   */
  consume(attemptId) {
    if (!attemptId) return null;
    this._prune();
    const v = this._mem.get(String(attemptId));
    if (!v) return null;
    this._mem.delete(String(attemptId));
    this._saveToDisk();
    return v.verifier || null;
  }
}

module.exports = { AuthAttemptStore };


