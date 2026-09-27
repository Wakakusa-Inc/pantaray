import http from 'http';
import type { AuthCallbackPayload, AuthCallbackResult } from './authCoordinator';
import type { RuntimeConfigLike } from './contracts';

type LoggerLike = {
  info?: (name: string, payload?: unknown) => void;
  warn?: (name: string, payload?: unknown) => void;
  error?: (name: string, payload?: unknown) => void;
};

export type LoopbackAuthTransport = {
  ensureStarted: () => Promise<{ ok: true } | { ok: false; error: string }>;
  buildRedirectUrl: (state: string) => string;
  stop: () => void;
};

function writePlainResponse(res: http.ServerResponse, statusCode: number, body: string): void {
  res.writeHead(statusCode, {
    'Content-Type': 'text/plain; charset=utf-8',
    'Cache-Control': 'no-store',
  });
  res.end(body);
}

export function createLoopbackAuthTransport(params: {
  port: number;
  ttlMs: number;
  callbackPath: string;
  getRuntimeConfig: () => RuntimeConfigLike | null;
  handleCallback: (payload: AuthCallbackPayload) => AuthCallbackResult;
  focusMainWindow?: () => void;
  onTimeout?: () => void;
  logger?: LoggerLike | null;
}): LoopbackAuthTransport {
  const logger = params.logger || null;
  const port = Math.floor(Number(params.port || 0));
  const ttlMs = Math.floor(Number(params.ttlMs || 0));
  const callbackPath = String(params.callbackPath || '/auth/callback');

  let server: http.Server | null = null;
  let timer: NodeJS.Timeout | null = null;
  let serverStartPromise: Promise<{ ok: true } | { ok: false; error: string }> | null = null;

  function clearTimer(): void {
    try {
      if (timer) clearTimeout(timer);
    } catch {
      // no-op
    }
    timer = null;
  }

  function scheduleTimeout(): void {
    clearTimer();
    timer = setTimeout(() => {
      logger?.warn?.('LOOPBACK_AUTH_TIMEOUT', { port, path: callbackPath });
      try {
        params.onTimeout?.();
      } catch {
        // no-op
      }
      stop();
    }, ttlMs);
  }

  function stop(): void {
    clearTimer();
    try {
      server?.close();
    } catch {
      // no-op
    }
    server = null;
  }

  function buildReturnUrl(): string | null {
    const cfg = params.getRuntimeConfig();
    const webAppOrigin = cfg ? String(cfg.web_app_origin || '').trim() : '';
    if (!webAppOrigin) return null;
    const returnUrl = new URL('/login', webAppOrigin);
    returnUrl.searchParams.set('desktop', '1');
    returnUrl.searchParams.set('desktop_return', '1');
    return returnUrl.toString();
  }

  function handleRequest(req: http.IncomingMessage, res: http.ServerResponse): void {
    try {
      const host = String(req.headers.host || '');
      const url = new URL(String(req.url || '/'), `http://${host}`);
      if (req.method !== 'GET' || url.pathname !== callbackPath) {
        writePlainResponse(res, 404, 'Not found');
        return;
      }

      const attemptId = (url.searchParams.get('attempt_id') || '').trim();
      const exchangeCode = (url.searchParams.get('exchange_code') || '').trim();
      const state = (url.searchParams.get('state') || '').trim();
      const returnUrl = buildReturnUrl();
      if (!returnUrl) {
        writePlainResponse(res, 500, 'Missing web_app_origin.');
        return;
      }

      const result = params.handleCallback({
        transport: 'loopback',
        attemptId,
        exchangeCode,
        state,
      });
      if (!result.ok) {
        writePlainResponse(res, result.statusCode, result.message);
        return;
      }

      res.writeHead(302, {
        Location: returnUrl,
        'Content-Type': 'text/plain; charset=utf-8',
        'Cache-Control': 'no-store',
      });
      res.end('Redirecting...');
      try {
        params.focusMainWindow?.();
      } catch {
        // no-op
      }
    } catch (e) {
      writePlainResponse(res, 500, 'Internal error');
      logger?.warn?.('LOOPBACK_AUTH_REQ_ERR', {
        err: e instanceof Error ? e.message : String(e),
      });
    }
  }

  function ensureStarted(): Promise<{ ok: true } | { ok: false; error: string }> {
    if (server && server.listening) {
      scheduleTimeout();
      return Promise.resolve({ ok: true });
    }
    if (serverStartPromise) return serverStartPromise;
    if (!Number.isFinite(port) || port <= 0) {
      return Promise.resolve({ ok: false, error: 'Invalid loopback port.' });
    }
    if (!Number.isFinite(ttlMs) || ttlMs <= 0) {
      return Promise.resolve({ ok: false, error: 'Invalid loopback ttl.' });
    }

    const promise = new Promise<{ ok: true } | { ok: false; error: string }>((resolve) => {
      let settled = false;
      const finalize = (result: { ok: true } | { ok: false; error: string }) => {
        if (settled) return;
        settled = true;
        resolve(result);
      };
      const onStartupError = (err: unknown) => {
        logger?.warn?.('LOOPBACK_AUTH_LISTEN_ERR', {
          port,
          path: callbackPath,
          err: err instanceof Error ? err.message : String(err),
        });
        stop();
        finalize({ ok: false, error: err instanceof Error ? err.message : String(err) });
      };
      const onServerError = (err: unknown) => {
        logger?.error?.('LOOPBACK_AUTH_SERVER_ERR', {
          err: err instanceof Error ? err.message : String(err),
        });
        stop();
      };

      try {
        server = http.createServer(handleRequest);
        server.once('error', onStartupError);
        server.listen(port, '127.0.0.1', () => {
          try {
            server?.off('error', onStartupError);
            server?.on('error', onServerError);
          } catch {
            // no-op
          }
          logger?.info?.('LOOPBACK_AUTH_LISTEN', { port, path: callbackPath });
          scheduleTimeout();
          finalize({ ok: true });
        });
      } catch (e) {
        stop();
        finalize({ ok: false, error: e instanceof Error ? e.message : String(e) });
      }
    }).finally(() => {
      serverStartPromise = null;
    });

    serverStartPromise = promise;
    return promise;
  }

  function buildRedirectUrl(state: string): string {
    return `http://127.0.0.1:${port}${callbackPath}?state=${encodeURIComponent(state)}`;
  }

  return { ensureStarted, buildRedirectUrl, stop };
}
