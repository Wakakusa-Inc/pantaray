const assert = require('node:assert/strict');
const http = require('node:http');
const net = require('node:net');
const { test } = require('node:test');

const { createAuthCoordinator } = require('../electron/dist/auth/authCoordinator.js');
const { createLoopbackAuthTransport } = require('../electron/dist/auth/loopbackAuth.js');

class MemoryAttemptStore {
  constructor() {
    this.items = new Map();
    MemoryAttemptStore.instances.push(this);
  }

  put(attemptId, verifier) {
    this.items.set(String(attemptId), String(verifier));
  }

  get(attemptId) {
    return this.items.get(String(attemptId)) || null;
  }

  consume(attemptId) {
    const key = String(attemptId);
    const verifier = this.items.get(key) || null;
    this.items.delete(key);
    return verifier;
  }
}
MemoryAttemptStore.instances = [];

function getFreePort() {
  return new Promise((resolve, reject) => {
    const server = net.createServer();
    server.once('error', reject);
    server.listen(0, '127.0.0.1', () => {
      const address = server.address();
      if (!address || typeof address === 'string') {
        server.close(() => reject(new Error('Failed to allocate a loopback port.')));
        return;
      }
      const port = address.port;
      server.close(() => resolve(port));
    });
  });
}

function requestStatus(url) {
  return new Promise((resolve, reject) => {
    const req = http.get(url, (res) => {
      res.resume();
      res.on('end', () => resolve(res.statusCode));
    });
    req.once('error', reject);
    req.setTimeout(2_000, () => {
      req.destroy(new Error('Timed out waiting for loopback response.'));
    });
  });
}

async function waitFor(predicate, message) {
  const deadline = Date.now() + 2_000;
  while (Date.now() < deadline) {
    if (predicate()) return;
    await new Promise((resolve) => setTimeout(resolve, 10));
  }
  throw new Error(message);
}

function createDeferred() {
  let resolve;
  let reject;
  const promise = new Promise((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

function jsonResponse(body, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    text: async () => JSON.stringify(body),
  };
}

function createDeferredExchangeFetch() {
  const requests = [];
  const fetchImpl = (_url, init = {}) => {
    const body = JSON.parse(String(init.body || '{}'));
    return new Promise((resolve, reject) => {
      requests.push({ body, resolve, reject });
    });
  };
  return { requests, fetchImpl };
}

function createLoopbackRuntimeConfig() {
  return {
    web_app_origin: 'https://pantaray.example.test',
    supabase_url: 'https://project.supabase.co',
    supabase_publishable_key: 'sb_publishable_test',
    backend_url: 'http://127.0.0.1:8005',
    api_host_origin: 'http://127.0.0.1:8005',
  };
}

function createHarness({ loopbackTransport, fetchImpl, applySessionTokens, accountLoginEnabled = true }) {
  let coordinator;
  const transport = loopbackTransport || {
    ensureStarted: async () => ({ ok: true }),
    buildRedirectUrl: (state) => `http://127.0.0.1:32100/auth/callback?state=${state}`,
    stop: () => {},
  };
  coordinator = createAuthCoordinator({
    accountLoginEnabled,
    AuthAttemptStore: MemoryAttemptStore,
    userDataDir: '/tmp/pantaray-test',
    safeStorage: null,
    ttlMs: 120_000,
    getRuntimeConfig: createLoopbackRuntimeConfig,
    getSupabaseSessionManager: () => ({
      applySessionTokens: applySessionTokens || (async () => ({ ok: true })),
    }),
    getLoopbackTransport: () => transport,
    fetchImpl,
  });
  return { coordinator, transport };
}

test('disabled Pantaray login rejects browser attempts and callbacks without an exchange', async () => {
  let exchangeCount = 0;
  const { coordinator } = createHarness({
    accountLoginEnabled: false,
    fetchImpl: async () => {
      exchangeCount += 1;
      return jsonResponse({ ok: true });
    },
  });

  assert.equal((await coordinator.startBrowserLogin('login')).ok, false);
  assert.deepStrictEqual(
    coordinator.handleCallback({
      transport: 'deep_link',
      attemptId: 'old-attempt',
      exchangeCode: 'old-code',
    }),
    { ok: false, statusCode: 409, message: 'Pantaray account login is disabled.' }
  );
  assert.equal(exchangeCount, 0);
});

test('auth coordinator rejects a superseded browser login after loopback startup resumes', async () => {
  const startupGate = createDeferred();
  let ensureStartedCount = 0;
  const transport = {
    ensureStarted: async () => {
      ensureStartedCount += 1;
      await startupGate.promise;
      return { ok: true };
    },
    buildRedirectUrl: (state) => `http://127.0.0.1:32100/auth/callback?state=${state}`,
    stop: () => {},
  };
  const { coordinator } = createHarness({
    loopbackTransport: transport,
    fetchImpl: async () => jsonResponse({ ok: false }, 500),
  });

  const first = coordinator.startBrowserLogin('login');
  await waitFor(() => ensureStartedCount === 1, 'first startup did not begin');
  const second = coordinator.startBrowserLogin('login');
  startupGate.resolve();

  const firstResult = await first;
  const secondResult = await second;
  assert.equal(firstResult.ok, false);
  assert.match(firstResult.error, /superseded/);
  assert.equal(secondResult.ok, true);
  assert.notEqual(firstResult.attempt_id, secondResult.attempt_id);
});

test('auth coordinator deduplicates duplicate loopback callbacks while exchange is in flight', async () => {
  const port = await getFreePort();
  const appliedTokens = [];
  const exchange = createDeferredExchangeFetch();
  let coordinator;
  const loopbackTransport = createLoopbackAuthTransport({
    port,
    ttlMs: 120_000,
    callbackPath: '/auth/callback',
    getRuntimeConfig: createLoopbackRuntimeConfig,
    handleCallback: (payload) => coordinator.handleCallback(payload),
  });
  ({ coordinator } = createHarness({
    loopbackTransport,
    fetchImpl: exchange.fetchImpl,
    applySessionTokens: async (tokens) => {
      appliedTokens.push(tokens);
      return { ok: true };
    },
  }));

  try {
    const attempt = await coordinator.startBrowserLogin('login');
    assert.equal(attempt.ok, true);
    const callbackUrl = new URL(attempt.loopback_redirect_url);
    callbackUrl.searchParams.set('attempt_id', attempt.attempt_id);
    callbackUrl.searchParams.set('exchange_code', 'exchange-1');

    assert.equal(await requestStatus(callbackUrl.toString()), 302);
    assert.equal(await requestStatus(callbackUrl.toString()), 302);
    await waitFor(
      () => exchange.requests.length === 1,
      'duplicate callback started a second exchange'
    );

    exchange.requests[0].resolve(
      jsonResponse({
        ok: true,
        tokens: { access_token: 'at', refresh_token: 'rt' },
        session_version: '1',
      })
    );
    await waitFor(() => appliedTokens.length === 1, 'session was not applied once');
  } finally {
    coordinator.dispose();
  }
});

test('auth coordinator rejects new browser login while tokens are being applied', async () => {
  const appliedTokens = [];
  const applyGate = createDeferred();
  const exchange = createDeferredExchangeFetch();
  const { coordinator } = createHarness({
    fetchImpl: exchange.fetchImpl,
    applySessionTokens: async (tokens) => {
      appliedTokens.push(tokens);
      await applyGate.promise;
      return { ok: true };
    },
  });

  try {
    const attempt = await coordinator.startBrowserLogin('login');
    assert.equal(attempt.ok, true);
    const accepted = coordinator.handleCallback({
      transport: 'loopback',
      attemptId: attempt.attempt_id,
      exchangeCode: 'exchange-1',
      state: new URL(attempt.loopback_redirect_url).searchParams.get('state') || '',
    });
    assert.equal(accepted.ok, true);
    await waitFor(() => exchange.requests.length === 1, 'exchange was not started');
    exchange.requests[0].resolve(
      jsonResponse({
        ok: true,
        tokens: { access_token: 'at', refresh_token: 'rt' },
        session_version: '1',
      })
    );
    await waitFor(() => appliedTokens.length === 1, 'apply was not started');

    const retry = await coordinator.startBrowserLogin('login');
    assert.equal(retry.ok, false);
    assert.equal(retry.error, 'Login session is already being applied.');
  } finally {
    applyGate.resolve();
    coordinator.dispose();
  }
});

test('auth coordinator routes deep link fallback through the same exchange and apply flow', async () => {
  const appliedTokens = [];
  const exchange = createDeferredExchangeFetch();
  const { coordinator } = createHarness({
    fetchImpl: exchange.fetchImpl,
    applySessionTokens: async (tokens) => {
      appliedTokens.push(tokens);
      return { ok: true };
    },
  });

  try {
    const attempt = await coordinator.startBrowserLogin('login');
    assert.equal(attempt.ok, true);
    const accepted = coordinator.handleCallback({
      transport: 'deep_link',
      attemptId: attempt.attempt_id,
      exchangeCode: 'exchange-1',
    });
    assert.equal(accepted.ok, true);
    await waitFor(() => exchange.requests.length === 1, 'deep link exchange was not started');
    assert.equal(exchange.requests[0].body.attempt_id, attempt.attempt_id);

    exchange.requests[0].resolve(
      jsonResponse({
        ok: true,
        tokens: { access_token: 'at', refresh_token: 'rt' },
        session_version: '1',
      })
    );
    await waitFor(() => appliedTokens.length === 1, 'deep link session was not applied');
  } finally {
    coordinator.dispose();
  }
});
