/**
 * SupabaseSessionManager
 *
 * Electron(main) で Supabase セッションを管理するためのユーティリティ。
 *
 * 目的:
 * - renderer に access/refresh token を渡さない（XSS 等での持ち出しリスクを下げる）
 * - アプリ再起動後もログイン維持（refresh token を OS の暗号化ストレージ相当へ保存）
 *
 * 方針:
 * - 永続化は main のみ（renderer/localStorage は使用しない）
 * - 保存時は Electron safeStorage で暗号化し、userData 配下へ書き込む
 */

const fs = require('fs');
const path = require('path');
const { EventEmitter } = require('events');
const { CredentialStorageError } = require('./dist/auth/encryptedJsonFile');

/**
 * @typedef {Object} PersistedTokens
 * @property {string} access_token
 * @property {string} refresh_token
 * @property {string} desktop_session_version
 */

/**
 * @typedef {Object} AuthState
 * @property {boolean} isLoggedIn
 * @property {{ id: string, email?: string | null } | null} user
 */

/**
 * @param {unknown} value
 * @returns {value is PersistedTokens}
 */
function isPersistedTokens(value) {
  if (!value || typeof value !== 'object') return false;
  return (
    typeof value.access_token === 'string' &&
    value.access_token.length > 0 &&
    typeof value.refresh_token === 'string' &&
    value.refresh_token.length > 0 &&
    typeof value.desktop_session_version === 'string' &&
    /^[1-9][0-9]*$/.test(value.desktop_session_version)
  );
}

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

class SupabaseSessionManager {
  /**
   * @param {Object} options
   * @param {(url: string, key: string, options?: any) => any} options.createClient - @supabase/supabase-js の createClient
   * @param {string} options.supabaseUrl - Supabase URL
   * @param {string} options.supabaseAnonKey - Supabase anon key (JWT)
   * @param {string} options.userDataDir - Electron app.getPath('userData')
   * @param {unknown} options.safeStorage - Electron safeStorage（依存注入）
   * @param {(token: unknown) => string | null} [options.extractUserIdFromJwt] - access token の sub を読む
   * @param {{ info?: Function, warn?: Function, error?: Function, debug?: Function }} [options.logger]
   */
  constructor(options) {
    this._createClient = options.createClient;
    this._extractUserIdFromJwt =
      typeof options.extractUserIdFromJwt === 'function' ? options.extractUserIdFromJwt : () => null;
    this._supabaseUrl = String(options.supabaseUrl || '').trim();
    this._supabaseAnonKey = String(options.supabaseAnonKey || '').trim();
    this._userDataDir = String(options.userDataDir || '').trim();
    this._safeStorage = options.safeStorage;
    this._logger = options.logger || console;

    this._storagePath = path.join(this._userDataDir, 'supabase-session.enc.json');
    this._emitter = new EventEmitter();

    this._supabase = null;
    /** @type {AuthState} */
    this._state = { authStatus: 'unauthenticated', isLoggedIn: false, user: null };
    this._accessToken = null;
    this._refreshToken = null;
    this._desktopSessionVersion = null;
    this._subscription = null;
    // signOut() の途中だけ true。SIGNED_OUT を明示ログアウトと失効で区別する。
    this._signingOut = false;
    /** @type {Promise<void>} */
    this._authChangeQueue = Promise.resolve();
    /** @type {{ userId: string, sessionVersion: string } | null} */
    this._expiredIdentity = null;
  }

  /**
   * 初期化する（client 作成 + 既存セッション復元 + 監視開始）。
   * @returns {Promise<void>}
   */
  async initialize() {
    if (!this._supabaseUrl || !this._supabaseAnonKey) {
      this._logger.warn?.(
        'SupabaseSessionManager: missing configuration (VITE_SUPABASE_URL / VITE_SUPABASE_PUBLISHABLE_KEY).'
      );
      return;
    }
    if (!this._userDataDir) {
      this._logger.warn?.('SupabaseSessionManager: missing userDataDir.');
      return;
    }

    this._supabase = this._createClient(this._supabaseUrl, this._supabaseAnonKey, {
      auth: {
        // 永続化は自前（safeStorage + file）で行うため、supabase-js の storage 永続は無効化する。
        persistSession: false,
        autoRefreshToken: true,
        detectSessionInUrl: false,
      },
      global: { headers: { 'x-application-name': 'pantaray-electron-main' } },
    });

    this._subscribeAuthState();
    await this._restoreSessionFromDisk();
  }

  /**
   * @returns {any | null}
   */
  getClient() {
    return this._supabase;
  }

  /**
   * @returns {AuthState}
   */
  getState() {
    return this._state;
  }

  /**
   * @returns {string | null}
   */
  getAccessToken() {
    return this._accessToken || null;
  }

  /**
   * @returns {string | null}
   */
  getDesktopSessionVersion() {
    return this._desktopSessionVersion || null;
  }

  /**
   * 更新できなくなったセッションのアカウント（失効中だけ非 null）。
   * @returns {{ userId: string, sessionVersion: string } | null}
   */
  getExpiredCloudIdentity() {
    return this._expiredIdentity;
  }

  /**
   * @private
   * @param {string | null} accessToken
   * @param {string | null} sessionVersion
   * @returns {{ userId: string, sessionVersion: string } | null}
   */
  _identityOf(accessToken, sessionVersion) {
    const userId = this._state.user?.id || this._extractUserIdFromJwt(accessToken);
    return userId && sessionVersion
      ? { userId: String(userId), sessionVersion: String(sessionVersion) }
      : null;
  }

  /**
   * 認証状態変更を購読する。
   * @param {(state: AuthState) => void} handler
   * @returns {() => void} unsubscribe
   */
  onStateChanged(handler) {
    const fn = typeof handler === 'function' ? handler : () => {};
    this._emitter.on('state', fn);
    return () => {
      try {
        this._emitter.off('state', fn);
      } catch {}
    };
  }

  /**
   * deep link 等で渡されたトークンを適用する（main 内で完結）。
   * @param {PersistedTokens} tokens
   * @returns {Promise<{ ok: boolean, error?: string }>}
   */
  async applySessionTokens(tokens) {
    const result = this._authChangeQueue.then(
      () => this._applySessionTokens(tokens),
      () => this._applySessionTokens(tokens)
    );
    this._authChangeQueue = result.then(() => undefined, () => undefined);
    return result;
  }

  /**
   * @private
   * @param {PersistedTokens} tokens
   * @returns {Promise<{ ok: boolean, error?: string }>}
   */
  async _applySessionTokens(tokens) {
    if (!this._supabase) {
      return { ok: false, error: 'Supabase client is not initialized.' };
    }
    if (!isPersistedTokens(tokens)) {
      return { ok: false, error: 'Invalid tokens.' };
    }
    try {
      this._desktopSessionVersion = tokens.desktop_session_version;
      const { error } = await this._supabase.auth.setSession({
        access_token: tokens.access_token,
        refresh_token: tokens.refresh_token,
      });
      if (error) {
        this._desktopSessionVersion = null;
        this._logger.warn?.('SupabaseSessionManager: setSession failed:', error);
        return { ok: false, error: String(error?.message || error) };
      }

      // setSession 後は onAuthStateChange が走るが、復元直後に落ちるケースを避けて即保存もしておく。
      this._persistTokensToDisk(tokens);
      return { ok: true };
    } catch (e) {
      this._desktopSessionVersion = null;
      this._logger.error?.('SupabaseSessionManager: applySessionTokens raised:', e);
      return { ok: false, error: e instanceof Error ? e.message : String(e) };
    }
  }

  /**
   * サインアウト。
   *
   * `reason: 'user'`（既定）は利用者の明示ログアウトで、保存済みセッションも削除する。
   * `reason: 'unauthorized'` はバックエンドがトークンを拒否したときの自動サインアウトで、
   * 失効として扱い、アカウントを identity として保持する。
   * @param {{ reason?: 'user' | 'unauthorized' }} [options]
   * @returns {Promise<void>}
   */
  async signOut(options) {
    // ログイン反映・明示ログアウト・401 による失効を直列化し、資格情報の保存と
    // 削除、SIGNED_OUT の理由を別の認証操作と混在させない。
    this._authChangeQueue = this._authChangeQueue.then(
      () => this._runSignOut(options),
      () => this._runSignOut(options)
    );
    return this._authChangeQueue;
  }

  /**
   * @private
   * @param {{ reason?: 'user' | 'unauthorized' }} [options]
   * @returns {Promise<void>}
   */
  async _runSignOut(options) {
    if (!this._supabase) return;
    const userInitiated = (options?.reason ?? 'user') === 'user';
    if (!userInitiated && !this._state.isLoggedIn && !this._expiredIdentity) {
      // 既にログアウト済みなら、拒否された要求は失効を作らない。
      return;
    }
    // Local recovery must not reinstall the old cloud token while remote revocation is pending.
    if (userInitiated) this._clearTokensFromDisk();
    this._signingOut = userInitiated;
    if (userInitiated) {
      this._expiredIdentity = null;
      this._desktopSessionVersion = null;
      this._updateState(null, 'unauthenticated');
    }
    try {
      await this._supabase.auth.signOut();
    } catch (e) {
      this._logger.warn?.('SupabaseSessionManager: signOut failed:', e);
    } finally {
      if (!userInitiated && this._state.authStatus !== 'expired') {
        // signOut がイベントを出さずに失敗しても、拒否されたトークンのまま
        // 認証済みに見せない。
        this._expiredIdentity =
          this._identityOf(this._accessToken, this._desktopSessionVersion) ??
          this._expiredIdentity;
        this._updateState(null, 'expired');
      }
      this._signingOut = false;
    }
  }

  /**
   * @private
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
   * @param {string} plain
   * @returns {string | null} base64 ciphertext
   */
  _encryptToBase64(plain) {
    if (!this._canEncrypt()) return null;
    try {
      const buf = this._safeStorage.encryptString(String(plain));
      return Buffer.isBuffer(buf) ? buf.toString('base64') : null;
    } catch (e) {
      this._logger.error?.('SupabaseSessionManager: encrypt failed:', e);
      return null;
    }
  }

  /**
   * @private
   * @param {string} b64
   * @returns {string | null}
   */
  _decryptFromBase64(b64) {
    if (!this._canEncrypt()) return null;
    try {
      const buf = Buffer.from(String(b64 || ''), 'base64');
      return this._safeStorage.decryptString(buf);
    } catch (e) {
      this._logger.warn?.('SupabaseSessionManager: decrypt failed:', e);
      return null;
    }
  }

  /**
   * @private
   * @param {PersistedTokens} tokens
   * @returns {void}
   */
  _persistTokensToDisk(tokens) {
    try {
      if (!isPersistedTokens(tokens)) return;
      const json = JSON.stringify({ v: 1, tokens }, null, 0);
      const cipherB64 = this._encryptToBase64(json);
      if (!cipherB64) {
        this._logger.warn?.(
          'SupabaseSessionManager: safeStorage encryption unavailable; session will not be persisted.'
        );
        return;
      }
      fs.writeFileSync(this._storagePath, JSON.stringify({ v: 1, ciphertext_b64: cipherB64 }, null, 2), {
        encoding: 'utf8',
        mode: 0o600,
      });
    } catch (e) {
      this._logger.error?.('SupabaseSessionManager: persist failed:', e);
    }
  }

  /**
   * @private
   * @returns {PersistedTokens | null}
   */
  _loadTokensFromDisk() {
    try {
      if (!fs.existsSync(this._storagePath)) return null;
      const raw = fs.readFileSync(this._storagePath, 'utf8');
      const parsed = JSON.parse(raw);
      const cipherB64 = parsed?.ciphertext_b64;
      if (!cipherB64 || typeof cipherB64 !== 'string') return null;
      const plain = this._decryptFromBase64(cipherB64);
      if (!plain) return null;
      const inner = JSON.parse(plain);
      const tokens = inner?.tokens;
      if (!isPersistedTokens(tokens)) return null;
      return tokens;
    } catch (e) {
      this._logger.warn?.('SupabaseSessionManager: load failed:', e);
      return null;
    }
  }

  /**
   * @private
   * @returns {void}
   */
  _clearTokensFromDisk() {
    try {
      fs.unlinkSync(this._storagePath);
    } catch (e) {
      if (e?.code !== 'ENOENT') throw new CredentialStorageError('delete_failed');
    }
  }

  /**
   * @private
   * @returns {Promise<void>}
   */
  async _restoreSessionFromDisk() {
    if (!this._supabase) return;
    const tokens = this._loadTokensFromDisk();
    if (!tokens) return;
    try {
      this._desktopSessionVersion = tokens.desktop_session_version;
      const { error } = await this._supabase.auth.setSession({
        access_token: tokens.access_token,
        refresh_token: tokens.refresh_token,
      });
      if (error) {
        this._markRestoreExpired(tokens);
        this._logger.warn?.('SupabaseSessionManager: restore setSession failed:', error);
        return;
      }
      // 正常に復元できた場合も、念のため最新状態を保存し直す（暗号方式/フォーマット変更に備える）。
      this._persistTokensToDisk(tokens);
    } catch (e) {
      this._markRestoreExpired(tokens);
      this._logger.warn?.('SupabaseSessionManager: restore raised:', e);
    }
  }

  /**
   * 保存済みセッションを復元できなかった: アカウントは分かるが更新できない（失効）。
   * @private
   * @param {PersistedTokens} tokens
   * @returns {void}
   */
  _markRestoreExpired(tokens) {
    this._desktopSessionVersion = null;
    if (this._state.isLoggedIn) return;
    this._expiredIdentity = this._identityOf(tokens.access_token, tokens.desktop_session_version);
    this._state = {
      authStatus: this._expiredIdentity ? 'expired' : 'unauthenticated',
      isLoggedIn: false,
      user: null,
    };
  }

  /**
   * @private
   * @param {any | null} session
   * @param {'unauthenticated' | 'expired'} [signedOutStatus] - session が無いときの状態
   * @returns {void}
   */
  _updateState(session, signedOutStatus = 'unauthenticated') {
    try {
      this._accessToken = session?.access_token ? String(session.access_token) : null;
      this._refreshToken = session?.refresh_token ? String(session.refresh_token) : null;
    } catch {
      this._accessToken = null;
      this._refreshToken = null;
    }
    const user = session?.user;
    if (user && typeof user === 'object') {
      const id = typeof user.id === 'string' ? user.id : '';
      const email = typeof user.email === 'string' ? user.email : null;
      this._expiredIdentity = null;
      this._state = {
        authStatus: id ? 'authenticated' : 'unauthenticated',
        isLoggedIn: Boolean(id),
        user: id ? { id, email } : null,
      };
    } else {
      this._state = { authStatus: signedOutStatus, isLoggedIn: false, user: null };
    }
    try {
      this._emitter.emit('state', this._state);
    } catch {}
  }

  /**
   * @private
   * @returns {void}
   */
  _subscribeAuthState() {
    if (!this._supabase) return;
    try {
      if (this._subscription && typeof this._subscription.unsubscribe === 'function') {
        this._subscription.unsubscribe();
      }
    } catch {}
    try {
      const { data } = this._supabase.auth.onAuthStateChange((event, session) => {
        // A refresh already in flight cannot undo an explicit local sign-out.
        if (this._signingOut && event !== 'SIGNED_OUT') return;
        // 自分で signOut() していない SIGNED_OUT は更新失敗（失効）。アカウントは覚えておく。
        const expired = event === 'SIGNED_OUT' && !this._signingOut;
        try {
          if (event === 'SIGNED_OUT') {
            if (expired) {
              // 続けて届いた 401 では token を既に捨てているので identity を
              // 導けない。最初に捉えたものを保持する。
              this._expiredIdentity =
                this._identityOf(this._accessToken, this._desktopSessionVersion) ??
                this._expiredIdentity;
              // 保存済みセッションは残す。再起動後の復元失敗から同じ失効
              // identity を読み直し、アカウントをローカルの所有者に保つ。
            } else {
              this._clearTokensFromDisk();
            }
            this._desktopSessionVersion = null;
          } else if (session?.access_token && session?.refresh_token) {
            if (!this._desktopSessionVersion) {
              throw new Error('desktop_session_version is missing.');
            }
            this._persistTokensToDisk({
              access_token: String(session.access_token),
              refresh_token: String(session.refresh_token),
              desktop_session_version: String(this._desktopSessionVersion),
            });
          }
        } catch {}
        this._updateState(session || null, expired ? 'expired' : 'unauthenticated');
      });
      this._subscription = data?.subscription || null;
    } catch (e) {
      this._logger.error?.('SupabaseSessionManager: onAuthStateChange subscription failed:', e);
    }
  }
}

module.exports = { SupabaseSessionManager };
