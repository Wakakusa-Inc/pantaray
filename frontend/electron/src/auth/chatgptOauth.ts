/**
 * ChatGPT ログインの OAuth クライアント（Electron main 専用）。
 *
 * OpenAI が公開している Codex CLI（openai/codex の codex-rs/login）と同じ公開
 * エンドポイントを自前で呼ぶ。外部エージェント実装には依存しない。
 * 秘密（verifier・トークン）はログに出さない。
 */

import { createHash, randomBytes } from 'node:crypto';
import http from 'node:http';

/** Codex CLI が公開している client。この client に登録された redirect だけが通る。 */
export const CHATGPT_OAUTH_CLIENT_ID = 'app_EMoamEEZ73f0CkXaXp7hrann';
/**
 * client 側に登録済みのポート。先頭から順に試す。Pantaray ログインの loopback 32100 とは別に立てる。
 * 予備は Codex CLI が同じ許可リストの登録済みポートとして使っているもの
 * （openai/codex の codex-rs/login/src/server.rs の FALLBACK_PORT）。同じ client を使う
 * 別のアプリがログインを実行している間は先頭が塞がるので、そちらを止めずに予備へ移る。
 */
export const CHATGPT_LOOPBACK_PORTS: readonly number[] = [1455, 1457];

const AUTH_ISSUER = 'https://auth.openai.com';
const CALLBACK_PATH = '/auth/callback';
const AUTHORIZE_SCOPE = 'openid profile email offline_access';
/** ChatGPT backend に名乗るクライアント識別子。ランタイムの transport と同じ値。 */
const ORIGINATOR = 'pantaray';
const OPENAI_AUTH_CLAIM = 'https://api.openai.com/auth';
/** 応答が来ないまま更新の余裕（5 分）を食い潰さないための上限。 */
const TOKEN_REQUEST_TIMEOUT_MS = 30_000;

export type ChatgptLogger = {
  warn?: (name: string, payload?: unknown) => void;
};

/** main だけが保持する一式。更新トークンはここから外へ出さない。 */
export type ChatgptTokens = {
  accessToken: string;
  refreshToken: string;
  accountId: string;
  /** アクセストークンの exp クレーム（ISO 8601）。 */
  expiresAt: string;
};

export type ChatgptTokenOutcome =
  | { ok: true; tokens: ChatgptTokens }
  /** `transient` なら同じ更新トークンで張り直せる。恒久的な失敗だけ再ログインが要る。 */
  | { ok: false; error: string; transient: boolean };

export type ChatgptAuthorizationRequest = {
  authorizeUrl: string;
  redirectUri: string;
  state: string;
  codeVerifier: string;
};

export type ChatgptCallbackError =
  | 'authorization_failed'
  /** 認可画面で拒否された（別アカウントの選択・取り消し）。 */
  | 'authorization_denied'
  /** そのアカウント／ワークスペースで Codex が有効でない。 */
  | 'missing_codex_entitlement'
  | 'authorization_timeout'
  | 'cancelled'
  | 'listener_unavailable';
export type ChatgptCallbackOutcome =
  | { ok: true; code: string }
  | { ok: false; error: ChatgptCallbackError };

export type ChatgptCallbackListener = {
  /** callback・期限切れ・stop のいずれかで必ず解決する。 */
  waitForCode: () => Promise<ChatgptCallbackOutcome>;
  stop: () => void;
};

// 交換と保存はこの応答のあとなので、ここでは認可が返ったことだけを伝える。
const CALLBACK_RECEIVED_PAGE =
  '<!doctype html><html lang="ja"><head><meta charset="utf-8"><title>Pantaray</title></head>' +
  '<body style="font-family:system-ui;padding:40px"><h1>ChatGPT の認可を受け取りました</h1>' +
  '<p>結果は Pantaray の画面で確認してください。このタブは閉じて構いません。</p></body></html>';

/** PKCE（S256）と state を生成し、認可 URL を組み立てる。 */
export function createAuthorizationRequest(port: number): ChatgptAuthorizationRequest {
  const codeVerifier = randomBytes(64).toString('base64url');
  const state = randomBytes(32).toString('base64url');
  // 127.0.0.1 で待ち受けるが、client に登録されているのは localhost 表記なのでそのまま送る。
  const redirectUri = `http://localhost:${port}${CALLBACK_PATH}`;
  const authorizeUrl = new URL('/oauth/authorize', AUTH_ISSUER);
  authorizeUrl.search = new URLSearchParams({
    response_type: 'code',
    client_id: CHATGPT_OAUTH_CLIENT_ID,
    redirect_uri: redirectUri,
    scope: AUTHORIZE_SCOPE,
    code_challenge: createHash('sha256').update(codeVerifier).digest('base64url'),
    code_challenge_method: 'S256',
    id_token_add_organizations: 'true',
    codex_cli_simplified_flow: 'true',
    state,
    originator: ORIGINATOR,
  }).toString();
  return { authorizeUrl: authorizeUrl.toString(), redirectUri, state, codeVerifier };
}

function writePlainResponse(res: http.ServerResponse, statusCode: number, body: string): void {
  res.writeHead(statusCode, {
    'Content-Type': 'text/plain; charset=utf-8',
    'Cache-Control': 'no-store',
  });
  res.end(body);
}

/**
 * 認可サーバーが返した拒否を、こちらの語彙に落とす。
 * サーバー由来の文字列は既知かどうかの判定にだけ使い、そのまま表示へは渡さない。
 */
function classifyCallbackDenial(query: URLSearchParams): ChatgptCallbackError | null {
  const error = (query.get('error') || '').trim();
  if (!error) return null;
  if (error !== 'access_denied') return 'authorization_failed';
  // Codex と同じ判定。権限がないのか、利用者が断ったのかで案内が変わる。
  const description = (query.get('error_description') || '').toLowerCase();
  return description.includes('missing_codex_entitlement')
    ? 'missing_codex_entitlement'
    : 'authorization_denied';
}

/**
 * `/auth/callback` だけを受けるワンショットの loopback サーバーを起動する。
 * state が一致しない要求は無視して待ち続ける。
 */
export function startChatgptCallbackListener(params: {
  port: number;
  expectedState: string;
  ttlMs: number;
  logger?: ChatgptLogger | null;
}): Promise<
  { ok: true; listener: ChatgptCallbackListener } | { ok: false; error: 'listener_unavailable' }
> {
  const logger = params.logger || null;
  const server = http.createServer(handleRequest);
  let settle: ((outcome: ChatgptCallbackOutcome) => void) | null = null;
  let timer: NodeJS.Timeout | null = null;
  const outcome = new Promise<ChatgptCallbackOutcome>((resolve) => {
    settle = resolve;
  });

  function finish(result: ChatgptCallbackOutcome): void {
    if (timer) clearTimeout(timer);
    timer = null;
    server.close();
    const resolve = settle;
    settle = null;
    resolve?.(result);
  }

  function handleRequest(req: http.IncomingMessage, res: http.ServerResponse): void {
    // 要求行はどんなバイト列でも来うるので、例外を投げる URL 解析は使わない。
    const [requestPath, rawQuery] = String(req.url || '/').split('?');
    if (req.method !== 'GET' || requestPath !== CALLBACK_PATH) {
      writePlainResponse(res, 404, 'Not found');
      return;
    }
    const query = new URLSearchParams(rawQuery || '');
    if (query.get('state') !== params.expectedState) {
      // 現在の試行のものではない応答。待ち受けは続ける。
      logger?.warn?.('CHATGPT_OAUTH_STATE_MISMATCH');
      writePlainResponse(res, 400, 'Invalid state.');
      return;
    }
    const denial = classifyCallbackDenial(query);
    if (denial) {
      writePlainResponse(res, 400, 'Login failed.');
      finish({ ok: false, error: denial });
      return;
    }
    const code = (query.get('code') || '').trim();
    if (!code) {
      writePlainResponse(res, 400, 'Login failed.');
      finish({ ok: false, error: 'authorization_failed' });
      return;
    }
    res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8', 'Cache-Control': 'no-store' });
    res.end(CALLBACK_RECEIVED_PAGE, () => finish({ ok: true, code }));
  }

  return new Promise((resolve) => {
    const onListenError = () => {
      server.close();
      resolve({ ok: false, error: 'listener_unavailable' });
    };
    server.once('error', onListenError);
    server.listen(params.port, '127.0.0.1', () => {
      server.off('error', onListenError);
      server.on('error', (err) => {
        logger?.warn?.('CHATGPT_OAUTH_SERVER_ERR', { err: err.message });
        finish({ ok: false, error: 'listener_unavailable' });
      });
      timer = setTimeout(() => finish({ ok: false, error: 'authorization_timeout' }), params.ttlMs);
      resolve({
        ok: true,
        listener: {
          waitForCode: () => outcome,
          stop: () => finish({ ok: false, error: 'cancelled' }),
        },
      });
    });
  });
}

/**
 * 登録済みのポートを先頭から試して待ち受けを立て、受けられたポートで認可要求を組む。
 * redirect は authorize と token 交換で同じ値でなければならないので、
 * ポートが決まってからしか作れない。
 */
export async function startChatgptAuthorization(params: {
  ports: readonly number[];
  ttlMs: number;
  logger?: ChatgptLogger | null;
}): Promise<
  | { ok: true; request: ChatgptAuthorizationRequest; listener: ChatgptCallbackListener }
  | { ok: false; error: 'listener_unavailable' }
> {
  for (const [index, port] of params.ports.entries()) {
    const request = createAuthorizationRequest(port);
    const started = await startChatgptCallbackListener({
      port,
      expectedState: request.state,
      ttlMs: params.ttlMs,
      logger: params.logger,
    });
    if (started.ok) {
      if (index > 0) params.logger?.warn?.('CHATGPT_OAUTH_FALLBACK_PORT', { port });
      return { ok: true, request, listener: started.listener };
    }
  }
  return { ok: false, error: 'listener_unavailable' };
}

/** JWT の署名は検証せず、必要なクレームだけを読む。 */
function readJwtClaims(token: string): Record<string, unknown> | null {
  const payload = token.split('.')[1];
  try {
    return JSON.parse(Buffer.from(String(payload), 'base64url').toString('utf8'));
  } catch {
    return null;
  }
}

function readChatgptAccountId(claims: Record<string, unknown> | null): string | null {
  const auth = claims?.[OPENAI_AUTH_CLAIM];
  const accountId =
    auth && typeof auth === 'object'
      ? (auth as Record<string, unknown>).chatgpt_account_id
      : undefined;
  return typeof accountId === 'string' && accountId.trim() ? accountId.trim() : null;
}

/**
 * 送信に要る account_id と期限を読む。期限はアクセストークンのものだけを使い、
 * account_id は Codex と同じく id_token にしか載っていない場合も拾う。
 */
function readTokenAttributes(
  accessToken: string,
  idToken: string | null
): { accountId: string; expiresAt: string } | null {
  const claims = readJwtClaims(accessToken);
  const accountId =
    readChatgptAccountId(claims) ?? (idToken ? readChatgptAccountId(readJwtClaims(idToken)) : null);
  const exp = claims?.exp;
  if (!accountId) return null;
  if (typeof exp !== 'number' || exp <= 0) return null;
  const expiresAt = new Date(exp * 1000);
  if (Number.isNaN(expiresAt.getTime())) return null;
  return { accountId, expiresAt: expiresAt.toISOString() };
}

/**
 * Codex と同じ分類。ここに挙げた失敗だけが更新トークンを使い切った状態で、
 * それ以外（通信断・5xx・読めない応答）はもう一度同じトークンで試せる。
 */
const PERMANENT_REFRESH_ERROR_CODES = new Set([
  'refresh_token_expired',
  'refresh_token_reused',
  'refresh_token_invalidated',
]);

async function readTokenErrorCode(response: Response): Promise<string> {
  let payload: unknown;
  try {
    payload = await response.json();
  } catch {
    return '';
  }
  if (!payload || typeof payload !== 'object') return '';
  const error = (payload as Record<string, unknown>).error;
  if (typeof error === 'string') return error;
  if (error && typeof error === 'object') {
    const code = (error as Record<string, unknown>).code;
    if (typeof code === 'string') return code;
  }
  return '';
}

function isPermanentRefreshFailure(status: number, code: string): boolean {
  if (status === 401) return true;
  if (PERMANENT_REFRESH_ERROR_CODES.has(code)) return true;
  return status === 400 && code === 'invalid_grant';
}

async function requestTokens(params: {
  fetchImpl: typeof fetch;
  headers: Record<string, string>;
  body: string;
  fallbackRefreshToken: string;
}): Promise<ChatgptTokenOutcome> {
  let response: Response;
  try {
    response = await params.fetchImpl(`${AUTH_ISSUER}/oauth/token`, {
      method: 'POST',
      headers: params.headers,
      body: params.body,
      signal: AbortSignal.timeout(TOKEN_REQUEST_TIMEOUT_MS),
    });
  } catch (e) {
    // 通信できていないだけなので、同じ更新トークンで張り直せる。
    return { ok: false, error: e instanceof Error ? e.message : String(e), transient: true };
  }
  if (!response.ok) {
    const code = await readTokenErrorCode(response);
    return {
      ok: false,
      error: `Token endpoint returned status ${response.status}.`,
      transient: !isPermanentRefreshFailure(response.status, code),
    };
  }
  let payload: unknown;
  try {
    payload = await response.json();
  } catch {
    return { ok: false, error: 'Token endpoint returned an unreadable body.', transient: true };
  }
  const body = payload && typeof payload === 'object' ? (payload as Record<string, unknown>) : null;
  const accessToken = body && typeof body.access_token === 'string' ? body.access_token : '';
  if (!accessToken) {
    return { ok: false, error: 'Token endpoint returned no access_token.', transient: true };
  }
  // 更新では refresh_token が返らないことがある。その場合は手元のものを使い続ける。
  const refreshToken =
    body && typeof body.refresh_token === 'string' && body.refresh_token
      ? body.refresh_token
      : params.fallbackRefreshToken;
  if (!refreshToken) {
    return { ok: false, error: 'Token endpoint returned no refresh_token.', transient: true };
  }
  // id_token は account_id を読むためだけに使い、保存も送信もしない。
  const idToken = body && typeof body.id_token === 'string' ? body.id_token : null;
  const attributes = readTokenAttributes(accessToken, idToken);
  if (!attributes) {
    return {
      ok: false,
      error: 'The tokens have no usable chatgpt_account_id or exp claim.',
      transient: true,
    };
  }
  return { ok: true, tokens: { accessToken, refreshToken, ...attributes } };
}

export function exchangeAuthorizationCode(params: {
  code: string;
  codeVerifier: string;
  redirectUri: string;
  fetchImpl: typeof fetch;
}): Promise<ChatgptTokenOutcome> {
  return requestTokens({
    fetchImpl: params.fetchImpl,
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: new URLSearchParams({
      grant_type: 'authorization_code',
      code: params.code,
      redirect_uri: params.redirectUri,
      client_id: CHATGPT_OAUTH_CLIENT_ID,
      code_verifier: params.codeVerifier,
    }).toString(),
    fallbackRefreshToken: '',
  });
}

export function refreshChatgptTokens(params: {
  refreshToken: string;
  fetchImpl: typeof fetch;
}): Promise<ChatgptTokenOutcome> {
  return requestTokens({
    fetchImpl: params.fetchImpl,
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      client_id: CHATGPT_OAUTH_CLIENT_ID,
      grant_type: 'refresh_token',
      refresh_token: params.refreshToken,
    }),
    fallbackRefreshToken: params.refreshToken,
  });
}
