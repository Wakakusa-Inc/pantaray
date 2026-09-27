/**
 * ChatGPT 接続の資格情報を Electron main が所有するための入口。
 *
 * ログイン・期限前更新・接続解除を 1 か所に閉じ、外へは「ランタイムへ渡してよい
 * 資格情報」だけを公開する。更新トークンはここから出さない。
 */

import {
  CHATGPT_LOOPBACK_PORTS,
  exchangeAuthorizationCode,
  refreshChatgptTokens,
  startChatgptAuthorization,
  type ChatgptLogger,
  type ChatgptCallbackError,
  type ChatgptTokens,
} from './chatgptOauth';
import type { ChatgptTokenStore, ChatgptTokenStoreResult } from './chatgptTokenStore';
import type { ChatgptCredential } from '../aiConnection/runtimeConnection';

/** 期限のこれだけ前に更新する（設計 6.6）。 */
const REFRESH_MARGIN_MS = 5 * 60 * 1000;
/** 更新の最短間隔。これを割るなら更新しても余裕が戻らない状態とみなす。 */
const MIN_REFRESH_INTERVAL_MS = 60 * 1000;
/**
 * 一時的な失敗のあと更新を張り直す間隔。Codex の HTTP 再試行と同じく 4 回・倍増で、
 * 合計 225 秒なので、すべての再試行が期限前の余裕（5 分）の内側に収まる。
 * 使い切ったら張り直さない。期限切れ後の送信はランタイムが拒否する。
 */
const REFRESH_RETRY_DELAYS_MS = [15_000, 30_000, 60_000, 120_000];
// 設計上の割り切り: setTimeout は 32 bit 上限を超える遅延を即時発火に丸めるので頭打ちにする。
// 24.85 日より先の期限を持つトークンは上限で一度更新するだけ（早いだけで害はない）。
// 実際にそこまで長寿命のアクセストークンが観測されたら、上限で刻んで張り直す。
const MAX_TIMER_DELAY_MS = 2_147_483_647;
/** ブラウザ側の操作（ワークスペース選択・2 要素認証）を見込んだ待ち時間。 */
const LOGIN_TTL_MS = 5 * 60 * 1000;

export type ChatgptLoginState =
  | { status: 'disconnected' }
  | { status: 'connected'; credential: ChatgptCredential }
  | { status: 'reauthentication_required'; account_id: string };

export type ChatgptSignInError =
  | ChatgptCallbackError
  | 'browser_open_failed'
  | 'token_exchange_failed'
  | Extract<ChatgptTokenStoreResult, { ok: false }>['error'];

export type ChatgptSignInResult =
  | { ok: true; credential: ChatgptCredential }
  | { ok: false; error: ChatgptSignInError };

export type ChatgptLogin = {
  getState: () => ChatgptLoginState;
  signIn: () => Promise<ChatgptSignInResult>;
  /** Stop only the pending attempt; a previously connected account stays connected. */
  cancelSignIn: () => void;
  /** ChatGPT のトークンだけを削除する。Pantaray アカウントや履歴には触れない。 */
  disconnect: () => ChatgptTokenStoreResult;
  dispose: () => void;
};

function toCredential(tokens: ChatgptTokens): ChatgptCredential {
  return {
    access_token: tokens.accessToken,
    expires_at: tokens.expiresAt,
    account_id: tokens.accountId,
  };
}

function computeRefreshDelayMs(expiresAt: string, nowMs: number): number {
  return Math.max(0, Date.parse(expiresAt) - REFRESH_MARGIN_MS - nowMs);
}

export function createChatgptLogin(params: {
  store: ChatgptTokenStore;
  openExternal: (url: string) => Promise<void>;
  onStateChanged: (state: ChatgptLoginState) => void;
  fetchImpl?: typeof fetch;
  ports?: readonly number[];
  logger?: ChatgptLogger | null;
}): ChatgptLogin {
  const logger = params.logger || null;
  const fetchImpl = params.fetchImpl || fetch;
  const ports = params.ports || CHATGPT_LOOPBACK_PORTS;

  let state: ChatgptLoginState = { status: 'disconnected' };
  let tokens: ChatgptTokens | null = null;
  let refreshTimer: NodeJS.Timeout | null = null;
  let pendingAttempt: { canceled: boolean; stop: () => void } | null = null;
  // 接続の世代。切断・再認証・再ログインで進み、進行中の更新の結果を無効にする。
  let generation = 0;
  let lastRefreshStartedAtMs = 0;
  let refreshRetries = 0;

  function setState(next: ChatgptLoginState): void {
    state = next;
    params.onStateChanged(next);
  }

  function clearRefreshTimer(): void {
    if (refreshTimer) clearTimeout(refreshTimer);
    refreshTimer = null;
  }

  function scheduleRefresh(delayMs: number, isRetry = false): void {
    clearRefreshTimer();
    refreshTimer = setTimeout(
      () => {
        // 更新には呼び出し元がいないので、ここで受けきる。
        refresh(isRetry).catch((e: unknown) => {
          logger?.warn?.('CHATGPT_OAUTH_REFRESH_ERROR', {
            err: e instanceof Error ? e.message : String(e),
          });
        });
      },
      Math.min(MAX_TIMER_DELAY_MS, delayMs)
    );
  }

  function cancelPendingAttempt(): void {
    const attempt = pendingAttempt;
    pendingAttempt = null;
    if (!attempt) return;
    attempt.canceled = true;
    attempt.stop();
  }

  function adopt(next: ChatgptTokens, isNewConnection: boolean): void {
    tokens = next;
    refreshRetries = 0;
    if (isNewConnection) {
      // 別の接続になるので、更新間隔の記録も引き継がない。
      generation += 1;
      lastRefreshStartedAtMs = 0;
    }
    setState({ status: 'connected', credential: toCredential(next) });
    scheduleRefresh(computeRefreshDelayMs(next.expiresAt, Date.now()));
  }

  function requireReauthentication(accountId: string, reason: string): void {
    clearRefreshTimer();
    tokens = null;
    generation += 1;
    logger?.warn?.('CHATGPT_OAUTH_REFRESH_FAILED', { reason });
    setState({ status: 'reauthentication_required', account_id: accountId });
  }

  async function refresh(isRetry: boolean): Promise<void> {
    const current = tokens;
    if (!current) return;
    const startedAtMs = Date.now();
    // 前回からこの間隔も空かないのは、更新しても余裕が戻らない状態（短寿命トークン、時計のずれ）。
    // 一時的な失敗の張り直しはこの間隔より短いので、区別して数えない。
    if (!isRetry && startedAtMs - lastRefreshStartedAtMs < MIN_REFRESH_INTERVAL_MS) {
      requireReauthentication(current.accountId, 'refreshing did not restore the expiry margin');
      return;
    }
    if (!isRetry) lastRefreshStartedAtMs = startedAtMs;
    const startedGeneration = generation;
    const result = await refreshChatgptTokens({ refreshToken: current.refreshToken, fetchImpl });
    // 切断・再認証・再ログインのあとに届いた結果は、古い接続のものなので捨てる。
    if (startedGeneration !== generation) return;
    if (!result.ok) {
      if (!result.transient) {
        requireReauthentication(current.accountId, result.error);
        return;
      }
      const retryDelayMs = REFRESH_RETRY_DELAYS_MS[refreshRetries];
      if (retryDelayMs === undefined) {
        // 張り直しを使い切った。接続はそのままで、期限切れ後の送信はランタイムが拒否する。
        clearRefreshTimer();
        logger?.warn?.('CHATGPT_OAUTH_REFRESH_UNREACHABLE', { reason: result.error });
        return;
      }
      refreshRetries += 1;
      logger?.warn?.('CHATGPT_OAUTH_REFRESH_RETRY', {
        reason: result.error,
        attempt: refreshRetries,
      });
      scheduleRefresh(retryDelayMs, true);
      return;
    }
    // 保存できなくてもこのセッションは続く。次回起動時は保存済みの古いトークンから始まる。
    const saved = params.store.save(result.tokens);
    if (!saved.ok) logger?.warn?.('CHATGPT_TOKEN_STORE_SAVE_FAILED', { reason: saved.error });
    adopt(result.tokens, false);
  }

  async function signIn(): Promise<ChatgptSignInResult> {
    cancelPendingAttempt();
    // 待ち受けの起動から交換の完了まで登録したままにして、切断や別のログインで中断できるようにする。
    const attempt = { canceled: false, stop: () => {} };
    pendingAttempt = attempt;
    try {
      const started = await startChatgptAuthorization({ ports, ttlMs: LOGIN_TTL_MS, logger });
      if (!started.ok) return { ok: false, error: attempt.canceled ? 'cancelled' : started.error };
      const { request } = started;
      attempt.stop = started.listener.stop;
      if (attempt.canceled) return { ok: false, error: 'cancelled' };

      try {
        await params.openExternal(request.authorizeUrl);
      } catch {
        return { ok: false, error: attempt.canceled ? 'cancelled' : 'browser_open_failed' };
      }

      const callback = await started.listener.waitForCode();
      if (attempt.canceled) return { ok: false, error: 'cancelled' };
      if (!callback.ok) return { ok: false, error: callback.error };

      const exchanged = await exchangeAuthorizationCode({
        code: callback.code,
        codeVerifier: request.codeVerifier,
        redirectUri: request.redirectUri,
        fetchImpl,
      });
      if (attempt.canceled) return { ok: false, error: 'cancelled' };
      if (!exchanged.ok) return { ok: false, error: 'token_exchange_failed' };

      const saved = params.store.save(exchanged.tokens);
      if (!saved.ok) return { ok: false, error: saved.error };
      adopt(exchanged.tokens, true);
      return { ok: true, credential: toCredential(exchanged.tokens) };
    } finally {
      if (pendingAttempt === attempt) pendingAttempt = null;
      attempt.stop();
    }
  }

  function disconnect(): ChatgptTokenStoreResult {
    // 消せていないのに切断を名乗ると、次回起動でトークンが戻ってしまう。
    const cleared = params.store.clear();
    if (!cleared.ok) return cleared;
    cancelPendingAttempt();
    clearRefreshTimer();
    tokens = null;
    generation += 1;
    setState({ status: 'disconnected' });
    return cleared;
  }

  function dispose(): void {
    cancelPendingAttempt();
    clearRefreshTimer();
    // 発行済みの更新が戻ってきてもタイマーを張り直さないよう、世代を進めて無効にする。
    generation += 1;
  }

  const stored = params.store.load();
  if (stored) {
    tokens = stored;
    const delayMs = computeRefreshDelayMs(stored.expiresAt, Date.now());
    // 期限の余裕を切っているトークンは、更新できるまで接続として公開しない。
    if (delayMs > 0) setState({ status: 'connected', credential: toCredential(stored) });
    scheduleRefresh(delayMs);
  }

  return { getState: () => state, signIn, cancelSignIn: cancelPendingAttempt, disconnect, dispose };
}
