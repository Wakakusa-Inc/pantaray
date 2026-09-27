const assert = require('node:assert/strict');
const { test } = require('node:test');
const http = require('node:http');
const { createSupabaseWiring } = require('../electron/dist/auth/supabaseWiring.js');
const { buildMainContext } = require('../electron/dist/ipc/mainContextFactory.js');
const { createLocalBackendClient } = require('../electron/dist/localBackend/client.js');
const tick = () => new Promise(resolve => setImmediate(resolve));
function deferred() {
  let resolve;
  const promise = new Promise(done => { resolve = done; });
  return { promise, resolve };
}
const signedOut = { authStatus: 'unauthenticated', isLoggedIn: false, user: null };
const account = id => ({ authStatus: 'authenticated', isLoggedIn: true, user: { id } });

function setup({ stop = async () => {}, clear = async () => ({ contained: true }), apply = async () => {}, remoteSignOut = async () => {} } = {}) {
  class SessionManager {
    static instance;
    constructor() {
      SessionManager.instance = this;
      this.state = signedOut;
      this.listeners = [];
      this.token = null;
      this.signOutCount = 0;
    }
    async initialize() {}
    getState() { return this.state; }
    getAccessToken() { return this.token; }
    getDesktopSessionVersion() { return this.token ? '1' : null; }
    onStateChanged(listener) { this.listeners.push(listener); }
    emit(state) {
      this.state = state;
      this.token = state.user ? `token-${state.user.id}` : null;
      for (const listener of this.listeners) listener(state);
    }
    async signOut() {
      this.signOutCount += 1;
      this.emit(signedOut);
      await remoteSignOut();
    }
  }
  const broadcasts = [];
  const applied = [];
  const retry = new Set();
  let helperOwner = 'guest';
  const wiring = createSupabaseWiring({
    accountLoginEnabled: true,
    createClient: () => ({}), SupabaseSessionManager: SessionManager,
    runtimeConfig: null, safeStorage: {}, userDataDir: '/tmp',
    extractUserIdFromJwt: () => null,
    beforeOwnerChanged: () => helperOwner === 'guest' ? Promise.resolve() : stop(),
    onLocalOwnerChanged: () => {},
    clearForSignOut: async () => { helperOwner = 'guest'; return clear(); },
    onAuthStateBroadcast: value => broadcasts.push(value),
    onAuthContextChanged: async context => {
      await apply(context);
      applied.push(context.userId);
      helperOwner = context.userId ?? 'guest';
    },
    getLocalConnectionStatus: async () => ({
      configured: true, activeOwnerId: helperOwner,
      cloudSessionState: helperOwner === 'guest' ? 'absent' : 'present',
    }),
    onLoginStatePersist: () => {},
    onOrchestrationDisconnect: () => {}, onOrchestrationReconnect: () => {},
    timers: {
      setTimeout: callback => { retry.add(callback); return callback; },
      clearTimeout: callback => retry.delete(callback),
    },
  });
  const context = buildMainContext({
    isDevRuntime: () => false, frontendDistIndex: '/tmp/index.html',
    getRuntimeState: wiring.getRuntimeState, getSupabaseSessionManager: wiring.getSessionManager,
    signOut: wiring.signOut,
  });
  return { wiring, context, broadcasts, applied, retry,
    owner: () => helperOwner, manager: () => SessionManager.instance,
    runRetry: async () => {
      assert.equal(retry.size, 1);
      const callback = [...retry][0]; retry.delete(callback); callback(); await tick();
    },
  };
}

test('logout stops the old source before clearing and blocks HTTP during clear acknowledgement and remote revocation', { timeout: 5000 }, async t => {
  const stopped = deferred();
  const stopReached = deferred();
  const cleared = deferred();
  const clearReached = deferred();
  const remote = deferred();
  t.after(() => { stopped.resolve(); cleared.resolve(); remote.resolve(); });
  const requests = [];
  let client;
  const fixture = setup({
    stop: async () => {
      const source = await client.requestJson({ path: '/v1/agents/users/alice/context-source', method: 'GET' });
      assert.equal(source.owner, 'alice');
      stopReached.resolve();
      await stopped.promise;
    },
    clear: async () => { clearReached.resolve(); await cleared.promise; return { contained: true }; },
    remoteSignOut: () => remote.promise,
  });
  const server = http.createServer((request, response) => {
    assert.equal(request.headers.authorization, 'Bearer local-test-token');
    requests.push(request.url);
    response.setHeader('Content-Type', 'application/json');
    response.end(JSON.stringify({ owner: fixture.owner() }));
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  t.after(() => new Promise(resolve => { server.closeAllConnections(); server.close(resolve); }));
  client = createLocalBackendClient({
    getRuntimeBackendUrl: () => `http://127.0.0.1:${server.address().port}`,
    getLocalApiToken: () => 'local-test-token', getRuntimeState: fixture.wiring.getRuntimeState,
  });
  await fixture.wiring.initialize();
  fixture.manager().emit(account('alice')); await tick();
  const loggingOut = fixture.context.auth.signOut();
  await stopReached.promise;
  assert.equal(fixture.context.auth.getState().runtimeState.owner, null);
  assert.deepEqual(fixture.broadcasts.at(-1).runtimeState, {
    status: 'ready', message: null, owner: null,
  });
  assert.equal(fixture.owner(), 'alice');
  stopped.resolve();
  await clearReached.promise;
  assert.equal(fixture.owner(), 'guest');
  assert.equal(fixture.context.auth.getState().runtimeState.owner, null);
  assert.equal(fixture.broadcasts.at(-1).runtimeState.status, 'syncing');
  assert.equal(fixture.manager().signOutCount, 0);
  await assert.rejects(client.requestJson({ path: '/api/agent/history', method: 'GET' }), /initializing/);
  cleared.resolve(); await tick();
  assert.equal(fixture.manager().getState().isLoggedIn, false);
  assert.equal(fixture.wiring.getRuntimeState().status, 'syncing');
  await assert.rejects(client.requestJson({ path: '/api/agent/history', method: 'GET' }), /initializing/);
  assert.deepEqual(requests, ['/v1/agents/users/alice/context-source']);
  remote.resolve();
  assert.deepEqual(await loggingOut, { ok: true }); await tick();
  assert.deepEqual(await client.requestJson({ path: '/api/agent/history', method: 'GET' }), { owner: 'guest' });
  assert.equal(fixture.wiring.getLocalOwnerId(), 'guest');
});

test('logout is serialized after an in-flight auth apply and cancels a superseded queued login', async () => {
  const applying = deferred();
  const clearing = deferred();
  let clearStarted = false;
  const fixture = setup({
    apply: context => context.userId === 'alice' ? applying.promise : undefined,
    clear: async () => { clearStarted = true; await clearing.promise; return { contained: true }; },
  });
  await fixture.wiring.initialize();
  fixture.manager().emit(account('alice')); await tick();
  const loggingOut = fixture.context.auth.signOut(); await tick();
  assert.equal(clearStarted, false);
  applying.resolve(); await tick();
  assert.equal(clearStarted, true);
  fixture.manager().emit(account('bob'));
  clearing.resolve();
  assert.deepEqual(await loggingOut, { ok: true }); await tick();
  assert.deepEqual(fixture.applied, [null, 'alice', null]);
  assert.equal(fixture.owner(), 'guest');
  assert.equal(fixture.wiring.getLocalOwnerId(), 'guest');
});

test('failed containment blocks cloud sign-out and restores the still-current account through retry', async () => {
  const fixture = setup({ clear: async () => ({ contained: false, reason: 'helper termination failed' }) });
  await fixture.wiring.initialize(); fixture.manager().emit(account('alice')); await tick();
  const result = await fixture.context.auth.signOut();
  assert.equal(result.ok, false); assert.match(result.error, /helper termination failed/);
  assert.equal(fixture.manager().signOutCount, 0);
  assert.equal(fixture.wiring.getRuntimeState().status, 'degraded');
  assert.equal(fixture.broadcasts.at(-1).runtimeState.owner, null);
  await fixture.runRetry();
  assert.equal(fixture.owner(), 'alice');
  assert.equal(fixture.wiring.getLocalOwnerId(), 'alice');
});

test('a failed recorder stop prevents auth replacement and is retried before switching accounts', async () => {
  let failed = false;
  const fixture = setup({ stop: async () => {
    if (!failed) { failed = true; throw new Error('recorder stop failed'); }
  } });
  await fixture.wiring.initialize(); fixture.manager().emit(account('alice')); await tick();
  fixture.manager().emit(account('bob')); await tick();
  assert.equal(fixture.owner(), 'alice');
  assert.equal(fixture.wiring.getRuntimeState().status, 'degraded');
  assert.equal(fixture.broadcasts.at(-1).runtimeState.owner, null);
  await fixture.runRetry();
  assert.equal(fixture.owner(), 'bob');
  assert.equal(fixture.wiring.getLocalOwnerId(), 'bob');
});

test('sign-out reconciles the local runtime even when the session manager emits no event', async () => {
  const fixture = setup();
  await fixture.wiring.initialize();
  fixture.manager().signOut = async () => {};
  assert.deepEqual(await fixture.context.auth.signOut(), { ok: true }); await tick();
  assert.equal(fixture.wiring.getLocalOwnerId(), 'guest');
  assert.equal(fixture.broadcasts.at(-1).runtimeState.status, 'ready');
  assert.equal(fixture.retry.size, 0);
});

test('failed logout cleanup retains the cloud session and allows a later logout after runtime recovery', async () => {
  let stopFails = true;
  let clearCount = 0;
  const fixture = setup({
    stop: async () => { if (stopFails) throw new Error('recorder still running'); },
    clear: async () => { clearCount += 1; return { contained: true }; },
  });
  await fixture.wiring.initialize(); fixture.manager().emit(account('alice')); await tick();
  assert.deepEqual(await fixture.context.auth.signOut(), { ok: false, error: 'recorder still running' });
  assert.equal(clearCount, 0);
  assert.equal(fixture.manager().signOutCount, 0);
  assert.equal(fixture.owner(), 'alice');
  assert.equal(fixture.wiring.getRuntimeState().status, 'degraded');
  await fixture.runRetry();
  stopFails = false;
  assert.deepEqual(await fixture.context.auth.signOut(), { ok: true }); await tick();
  assert.equal(clearCount, 1);
  assert.equal(fixture.wiring.getLocalOwnerId(), 'guest');
});
