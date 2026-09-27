import { createHash, randomBytes, randomUUID } from 'crypto';
import type { RuntimeConfigLike, SupabaseSessionManagerLike } from './contracts';

export type AuthAttemptStoreLike = {
  put?: (attemptId: string, verifier: string) => void;
  get?: (attemptId: string) => string | null;
  consume?: (attemptId: string) => string | null;
};

export type AuthAttemptStoreCtor = new (opts: unknown) => AuthAttemptStoreLike;

export type AuthCallbackTransport = 'loopback' | 'deep_link';

export type AuthCallbackPayload = {
  transport: AuthCallbackTransport;
  attemptId: string;
  exchangeCode: string;
  state?: string;
};

export type BrowserLoginRoute = 'login' | 'signup' | 'forgot-password';

export type BrowserLoginResult =
  | {
      ok: true;
      attempt_id: string;
      code_challenge: string;
      route: BrowserLoginRoute;
      loopback_redirect_url: string;
    }
  | { ok: false; error: string };

export type AuthCallbackResult =
  | { ok: true }
  | { ok: false; statusCode: 400 | 409 | 500; message: string };

type AttemptStatus =
  | 'waiting_callback'
  | 'exchanging'
  | 'applying'
  | 'completed'
  | 'failed'
  | 'cancelled';

type AttemptContext = {
  attemptId: string;
  state: string;
  codeVerifier: string;
  codeChallenge: string;
  route: BrowserLoginRoute;
  createdAtMs: number;
  expiresAtMs: number;
  status: AttemptStatus;
  exchangeCode: string | null;
};

type LoggerLike = {
  info?: (name: string, payload?: unknown) => void;
  warn?: (name: string, payload?: unknown) => void;
  error?: (name: string, payload?: unknown) => void;
  debug?: (name: string, payload?: unknown) => void;
};

type LoopbackTransportLike = {
  ensureStarted: () => Promise<{ ok: true } | { ok: false; error: string }>;
  buildRedirectUrl: (state: string) => string;
  stop: () => void;
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object';
}

function safeParseJson(rawText: string): unknown {
  try {
    return rawText ? JSON.parse(rawText) : null;
  } catch {
    return null;
  }
}

function normalizeRoute(route: unknown): BrowserLoginRoute {
  if (route === 'signup' || route === 'forgot-password') return route;
  return 'login';
}

function createCodeChallenge(verifier: string): string {
  return createHash('sha256').update(verifier).digest('base64url');
}

function isPositiveIntegerString(value: string): boolean {
  return /^[1-9][0-9]*$/.test(value);
}

export function createAuthCoordinator(params: {
  accountLoginEnabled: boolean;
  AuthAttemptStore: AuthAttemptStoreCtor;
  userDataDir: string;
  safeStorage: unknown;
  ttlMs: number;
  getRuntimeConfig: () => RuntimeConfigLike | null;
  getSupabaseSessionManager: () => SupabaseSessionManagerLike | null;
  getLoopbackTransport: () => LoopbackTransportLike;
  focusMainWindow?: () => void;
  logger?: LoggerLike | null;
  fetchImpl?: typeof fetch;
}) {
  const logger = params.logger || null;
  const fetchImpl = params.fetchImpl || fetch;
  const ttlMs = Math.floor(Number(params.ttlMs || 0));

  let store: AuthAttemptStoreLike | null = null;
  let currentAttempt: AttemptContext | null = null;
  let pendingCallback: AuthCallbackPayload | null = null;

  function ensureStore(): AuthAttemptStoreLike | null {
    if (store) return store;
    try {
      store = new params.AuthAttemptStore({
        userDataDir: params.userDataDir,
        safeStorage: params.safeStorage,
        ttlMs,
        logger: logger ?? console,
      });
      return store;
    } catch (e) {
      logger?.warn?.('AUTH_COORDINATOR_STORE_UNAVAILABLE', {
        err: e instanceof Error ? e.message : String(e),
      });
      return null;
    }
  }

  function consumeVerifier(attemptId: string): string | null {
    try {
      const id = String(attemptId || '').trim();
      if (!id) return null;
      const st = ensureStore();
      const verifier = st?.consume?.(id);
      return verifier && typeof verifier === 'string' ? verifier : null;
    } catch {
      return null;
    }
  }

  function getVerifier(attemptId: string): string | null {
    try {
      const id = String(attemptId || '').trim();
      if (!id) return null;
      if (currentAttempt?.attemptId === id) return currentAttempt.codeVerifier;
      const st = ensureStore();
      const verifier = st?.get?.(id) ?? null;
      return verifier && typeof verifier === 'string' ? verifier : null;
    } catch {
      return null;
    }
  }

  function clearStoredAttempt(attemptId: string): void {
    consumeVerifier(attemptId);
  }

  function isCurrent(context: AttemptContext): boolean {
    return currentAttempt === context && context.status !== 'cancelled';
  }

  function cancelCurrentAttempt(): void {
    const context = currentAttempt;
    if (!context) return;
    context.status = 'cancelled';
    clearStoredAttempt(context.attemptId);
    currentAttempt = null;
    pendingCallback = null;
  }

  function expireCurrentAttempt(): void {
    const context = currentAttempt;
    if (!context) return;
    if (Date.now() <= context.expiresAtMs) return;
    context.status = 'failed';
    clearStoredAttempt(context.attemptId);
    currentAttempt = null;
    pendingCallback = null;
    params.getLoopbackTransport().stop();
  }

  async function startBrowserLogin(route: unknown): Promise<BrowserLoginResult> {
    if (!params.accountLoginEnabled) {
      return { ok: false, error: 'Pantaray account login is disabled.' };
    }
    expireCurrentAttempt();
    if (currentAttempt?.status === 'applying') {
      return { ok: false, error: 'Login session is already being applied.' };
    }
    cancelCurrentAttempt();

    if (!Number.isFinite(ttlMs) || ttlMs <= 0) {
      return { ok: false, error: 'Invalid auth attempt ttl.' };
    }

    const attemptId = randomUUID();
    const codeVerifier = randomBytes(32).toString('base64url');
    const context: AttemptContext = {
      attemptId,
      state: randomBytes(16).toString('hex'),
      codeVerifier,
      codeChallenge: createCodeChallenge(codeVerifier),
      route: normalizeRoute(route),
      createdAtMs: Date.now(),
      expiresAtMs: Date.now() + ttlMs,
      status: 'waiting_callback',
      exchangeCode: null,
    };

    const st = ensureStore();
    if (!st) return { ok: false, error: 'AuthAttemptStore is not available.' };
    st.put?.(context.attemptId, context.codeVerifier);
    currentAttempt = context;

    const transport = params.getLoopbackTransport();
    const started = await transport.ensureStarted();
    if (!started.ok) {
      if (isCurrent(context)) currentAttempt = null;
      clearStoredAttempt(context.attemptId);
      return { ok: false, error: started.error };
    }
    if (!isCurrent(context)) {
      return { ok: false, error: 'Login attempt was superseded.' };
    }

    return {
      ok: true,
      attempt_id: context.attemptId,
      code_challenge: context.codeChallenge,
      route: context.route,
      loopback_redirect_url: transport.buildRedirectUrl(context.state),
    };
  }

  function getLoopbackReturnResult(payload: AuthCallbackPayload): AuthCallbackResult {
    expireCurrentAttempt();
    const context = currentAttempt;
    if (!context || payload.attemptId !== context.attemptId || payload.state !== context.state) {
      return { ok: false, statusCode: 400, message: 'Invalid state.' };
    }
    return acceptCallback(context, payload);
  }

  function acceptCallback(
    context: AttemptContext,
    payload: AuthCallbackPayload
  ): AuthCallbackResult {
    if (context.status === 'completed') return { ok: true };
    if (context.status === 'failed' || context.status === 'cancelled') {
      return { ok: false, statusCode: 409, message: 'Login attempt is no longer active.' };
    }
    if (Date.now() > context.expiresAtMs) {
      expireCurrentAttempt();
      return { ok: false, statusCode: 400, message: 'Login attempt expired.' };
    }

    const exchangeCode = String(payload.exchangeCode || '').trim();
    if (!exchangeCode) {
      return { ok: false, statusCode: 400, message: 'Missing parameters.' };
    }
    if (context.exchangeCode && context.exchangeCode !== exchangeCode) {
      return { ok: false, statusCode: 409, message: 'Different exchange_code is already active.' };
    }
    if (context.status === 'exchanging' || context.status === 'applying') return { ok: true };

    context.exchangeCode = exchangeCode;
    context.status = 'exchanging';
    pendingCallback = null;
    void exchangeAndApply(context, payload.transport);
    return { ok: true };
  }

  function handleDeepLinkCallback(payload: AuthCallbackPayload): AuthCallbackResult {
    expireCurrentAttempt();
    const attemptId = String(payload.attemptId || '').trim();
    if (!attemptId) return { ok: false, statusCode: 400, message: 'Missing parameters.' };

    if (currentAttempt?.attemptId === attemptId) {
      return acceptCallback(currentAttempt, payload);
    }

    const verifier = getVerifier(attemptId);
    if (!verifier) {
      pendingCallback = payload;
      return { ok: false, statusCode: 409, message: 'Login attempt is not ready.' };
    }

    const context: AttemptContext = {
      attemptId,
      state: '',
      codeVerifier: verifier,
      codeChallenge: createCodeChallenge(verifier),
      route: 'login',
      createdAtMs: Date.now(),
      expiresAtMs: Date.now() + ttlMs,
      status: 'waiting_callback',
      exchangeCode: null,
    };
    currentAttempt = context;
    return acceptCallback(context, payload);
  }

  function handleCallback(payload: AuthCallbackPayload): AuthCallbackResult {
    if (!params.accountLoginEnabled) {
      return { ok: false, statusCode: 409, message: 'Pantaray account login is disabled.' };
    }
    const normalized: AuthCallbackPayload = {
      transport: payload.transport,
      attemptId: String(payload.attemptId || '').trim(),
      exchangeCode: String(payload.exchangeCode || '').trim(),
      state: typeof payload.state === 'string' ? payload.state.trim() : undefined,
    };
    if (!normalized.attemptId || !normalized.exchangeCode) {
      return { ok: false, statusCode: 400, message: 'Missing parameters.' };
    }
    if (normalized.transport === 'loopback') return getLoopbackReturnResult(normalized);
    return handleDeepLinkCallback(normalized);
  }

  async function applyPendingCallback(): Promise<void> {
    const payload = pendingCallback;
    if (!payload) return;
    handleCallback(payload);
  }

  async function exchangeAndApply(
    context: AttemptContext,
    transport: AuthCallbackTransport
  ): Promise<void> {
    try {
      const mgr = params.getSupabaseSessionManager();
      const applySessionTokens = mgr?.applySessionTokens;
      if (!applySessionTokens) {
        pendingCallback = {
          transport,
          attemptId: context.attemptId,
          exchangeCode: context.exchangeCode || '',
          state: context.state || undefined,
        };
        context.status = 'waiting_callback';
        return;
      }

      const cfg = params.getRuntimeConfig();
      const supabaseUrl = cfg ? String(cfg.supabase_url || '').trim() : '';
      const publishableKey = cfg ? String(cfg.supabase_publishable_key || '').trim() : '';
      if (!supabaseUrl || !publishableKey) {
        context.status = 'failed';
        logger?.warn?.('AUTH_COORDINATOR_CONFIG_MISSING', { transport });
        return;
      }

      const verifier = getVerifier(context.attemptId);
      if (!verifier || !isCurrent(context)) return;

      const endpoint = `${supabaseUrl.replace(/\/$/, '')}/functions/v1/desktop_auth/exchange`;
      const resp = await fetchImpl(endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', apikey: publishableKey },
        body: JSON.stringify({
          attempt_id: context.attemptId,
          exchange_code: context.exchangeCode,
          code_verifier: verifier,
        }),
      });
      const rawText = await resp.text().catch(() => '');
      if (!isCurrent(context)) return;

      const json = safeParseJson(rawText);
      const j = isRecord(json) ? json : null;
      if (!resp.ok || !j || j.ok !== true) {
        context.status = 'failed';
        logger?.warn?.('AUTH_COORDINATOR_EXCHANGE_FAIL', {
          transport,
          status: resp.status,
          body_fp: rawText ? rawText.length : 0,
        });
        return;
      }

      const tokens = isRecord(j.tokens) ? j.tokens : null;
      const accessToken =
        tokens && typeof tokens.access_token === 'string' ? tokens.access_token : '';
      const refreshToken =
        tokens && typeof tokens.refresh_token === 'string' ? tokens.refresh_token : '';
      const sessionVersion = typeof j.session_version === 'string' ? j.session_version.trim() : '';
      if (
        !accessToken ||
        !refreshToken ||
        !isPositiveIntegerString(sessionVersion) ||
        !isCurrent(context)
      ) {
        context.status = 'failed';
        return;
      }

      context.status = 'applying';
      const res = await applySessionTokens.call(mgr, {
        access_token: accessToken,
        refresh_token: refreshToken,
        desktop_session_version: sessionVersion,
      });
      if (!isCurrent(context)) return;
      if (!res || res.ok !== true) {
        context.status = 'failed';
        logger?.warn?.('AUTH_COORDINATOR_APPLY_FAIL', {
          transport,
          err: (res as { error?: unknown } | null)?.error || null,
        });
        return;
      }

      context.status = 'completed';
      clearStoredAttempt(context.attemptId);
      currentAttempt = null;
      pendingCallback = null;
      params.getLoopbackTransport().stop();
      try {
        params.focusMainWindow?.();
      } catch {
        // no-op
      }
      logger?.info?.('AUTH_COORDINATOR_OK', { transport });
    } catch (e) {
      if (isCurrent(context)) context.status = 'failed';
      logger?.warn?.('AUTH_COORDINATOR_ERR', {
        transport,
        err: e instanceof Error ? e.message : String(e),
      });
    }
  }

  function dispose(): void {
    cancelCurrentAttempt();
    params.getLoopbackTransport().stop();
  }

  return {
    startBrowserLogin,
    handleCallback,
    applyPendingCallback,
    expireCurrentAttempt,
    dispose,
  };
}
