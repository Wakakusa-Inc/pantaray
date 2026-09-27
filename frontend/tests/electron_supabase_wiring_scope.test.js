const assert = require('assert');
const { test } = require('node:test');

const { createSupabaseWiring } = require('../electron/dist/auth/supabaseWiring.js');
const ownerCallbacks = { beforeOwnerChanged: async () => {}, onLocalOwnerChanged: () => {} };

function configuredStatus(manager) {
  const accountId = manager?.getState?.().user?.id ?? manager?.getExpiredCloudIdentity?.()?.userId;
  return { configured: true, activeOwnerId: accountId ?? 'guest-owner', helperInstanceId: 'helper-1',
    cloudSessionState: accountId ? 'present' : 'absent' };
}

function createSupabaseSessionManagerStub() {
  class SupabaseSessionManagerStub {
    static lastInstance = null;

    constructor() {
      this._state = { isLoggedIn: false, user: null };
      this._token = null;
      this._sessionVersion = null;
      this._listeners = [];
      SupabaseSessionManagerStub.lastInstance = this;
    }

    async initialize() {}

    getState() {
      return this._state;
    }

    getAccessToken() {
      return this._token;
    }

    getDesktopSessionVersion() {
      return this._sessionVersion;
    }

    onStateChanged(handler) {
      this._listeners.push(handler);
      return () => {};
    }

    emit(state, token, sessionVersion = null) {
      this._state = state;
      this._token = token;
      this._sessionVersion = sessionVersion;
      for (const listener of this._listeners) {
        listener(state);
      }
    }
  }

  return {
    SupabaseSessionManagerStub,
    getInstance: () => SupabaseSessionManagerStub.lastInstance,
  };
}

function createFakeTimers() {
  const scheduled = [];
  let nextId = 1;
  return {
    scheduled,
    api: {
      setTimeout: (callback, delayMs) => {
        const handle = { id: nextId++, callback, delayMs };
        scheduled.push(handle);
        return handle;
      },
      clearTimeout: (handle) => {
        const index = scheduled.findIndex((entry) => entry.id === handle.id);
        if (index >= 0) {
          scheduled.splice(index, 1);
        }
      },
    },
    async runNext() {
      const next = scheduled.shift();
      if (!next) {
        return;
      }
      await next.callback();
    },
  };
}

test('disabled Pantaray login starts the guest runtime without restoring a saved session', async () => {
  const broadcasts = [];
  const contexts = [];
  const wiring = createSupabaseWiring({
    accountLoginEnabled: false,
    ...ownerCallbacks,
    createClient: () => { throw new Error('Supabase client must not start'); },
    SupabaseSessionManager: class {
      constructor() { throw new Error('Saved account session must not be restored'); }
    },
    runtimeConfig: null,
    safeStorage: {},
    userDataDir: '/tmp',
    extractUserIdFromJwt: () => null,
    onAuthStateBroadcast: (state) => broadcasts.push(state),
    onAuthContextChanged: async (context) => contexts.push(context),
    getLocalConnectionStatus: async () => configuredStatus(null),
    onLoginStatePersist: () => {},
    onOrchestrationDisconnect: () => {},
    onOrchestrationReconnect: () => {},
  });

  await wiring.initialize();

  assert.equal(wiring.getInitializationStatus(), 'ready');
  assert.equal(wiring.getSessionManager(), null);
  assert.deepStrictEqual(contexts, [
    { token: null, userId: null, sessionVersion: null, expiredIdentity: null },
  ]);
  assert.deepStrictEqual(broadcasts.at(-1), {
    authStatus: 'unauthenticated',
    isLoggedIn: false,
    user: null,
    runtimeState: { status: 'ready', message: null, owner: { id: 'guest-owner', kind: 'guest' } },
  });
});

test('supabaseWiring: session manager stays private until restore completes', async () => {
  let resolveInitialize;

  class SlowSupabaseSessionManagerStub {
    async initialize() {
      await new Promise((resolve) => {
        resolveInitialize = resolve;
      });
    }

    getState() {
      return { isLoggedIn: true, user: { id: 'user_a' } };
    }

    getAccessToken() {
      return 'token-a';
    }

    onStateChanged() {
      return () => {};
    }
  }

  const broadcasts = [];
  const wiring = createSupabaseWiring({
    accountLoginEnabled: true,
    ...ownerCallbacks,
    onAuthContextChanged: async () => {},
    getLocalConnectionStatus: async () => configuredStatus(wiring.getSessionManager()),
    createClient: () => ({}),
    SupabaseSessionManager: SlowSupabaseSessionManagerStub,
    runtimeConfig: {
      supabase_url: 'https://example.supabase.co',
      supabase_publishable_key: 'sb_publishable_test',
    },
    safeStorage: {},
    userDataDir: '/tmp',
    extractUserIdFromJwt: () => null,
    onAuthStateBroadcast: (state) => {
      broadcasts.push(state);
    },
    onAuthTokenChanged: () => {},
    onLoginStatePersist: () => {},
    onOrchestrationDisconnect: () => {},
    onOrchestrationReconnect: () => {},
  });

  const initializePromise = wiring.initialize();
  await new Promise((resolve) => setImmediate(resolve));

  assert.equal(wiring.getSessionManager(), null);
  assert.deepStrictEqual(broadcasts, []);

  resolveInitialize();
  await initializePromise;

  assert.ok(wiring.getSessionManager(), 'SupabaseSessionManager should be public after restore');
  assert.deepStrictEqual(broadcasts.at(-1), {
    authStatus: 'authenticated',
    isLoggedIn: true,
    user: { id: 'user_a' },
    runtimeState: { status: 'ready', message: null, owner: { id: 'user_a', kind: 'account' } },
  });
});

test('supabaseWiring: initialization failure still leaves the local runtime usable', async () => {
  class FailingSupabaseSessionManagerStub {
    async initialize() {
      throw new Error('restore failed');
    }
  }

  const broadcasts = [];
  const wiring = createSupabaseWiring({
    accountLoginEnabled: true,
    ...ownerCallbacks,
    onAuthContextChanged: async () => {},
    getLocalConnectionStatus: async () => configuredStatus(wiring.getSessionManager()),
    createClient: () => ({}),
    SupabaseSessionManager: FailingSupabaseSessionManagerStub,
    runtimeConfig: {
      supabase_url: 'https://example.supabase.co',
      supabase_publishable_key: 'sb_publishable_test',
    },
    safeStorage: {},
    userDataDir: '/tmp',
    extractUserIdFromJwt: () => null,
    onAuthStateBroadcast: (state) => {
      broadcasts.push(state);
    },
    onAuthTokenChanged: () => {},
    onLoginStatePersist: () => {},
    onOrchestrationDisconnect: () => {},
    onOrchestrationReconnect: () => {},
  });

  await wiring.initialize();

  assert.equal(wiring.getInitializationStatus(), 'failed');
  assert.equal(wiring.getSessionManager(), null);
  assert.deepStrictEqual(broadcasts.at(-1), {
    authStatus: 'unauthenticated',
    isLoggedIn: false,
    user: null,
    runtimeState: { status: 'ready', message: null, owner: { id: 'guest-owner', kind: 'guest' } },
  });
});

test('supabaseWiring: onAuthContextChanged receives token and user after state normalization', async () => {
  const events = [];
  const { SupabaseSessionManagerStub, getInstance } = createSupabaseSessionManagerStub();

  const wiring = createSupabaseWiring({
    accountLoginEnabled: true,
    ...ownerCallbacks,
    getLocalConnectionStatus: async () => configuredStatus(wiring.getSessionManager()),
    createClient: () => ({}),
    SupabaseSessionManager: SupabaseSessionManagerStub,
    runtimeConfig: {
      supabase_url: 'https://example.supabase.co',
      supabase_publishable_key: 'sb_publishable_test',
    },
    safeStorage: {},
    userDataDir: '/tmp',
    extractUserIdFromJwt: () => null,
    onAuthStateBroadcast: () => {},
    onAuthTokenChanged: () => {},
    onAuthContextChanged: async (payload) => {
      events.push(payload);
    },
    onLoginStatePersist: () => {},
    onOrchestrationDisconnect: () => {},
    onOrchestrationReconnect: () => {},
  });

  await wiring.initialize();
  const mgr = getInstance();
  assert.ok(mgr, 'SupabaseSessionManager instance is required');

  mgr.emit({ isLoggedIn: true, user: { id: 'user_a' } }, 'token-a', '7');
  await new Promise((resolve) => setImmediate(resolve));

  assert.deepStrictEqual(events, [
    { token: null, userId: null, sessionVersion: null, expiredIdentity: null },
    { token: 'token-a', userId: 'user_a', sessionVersion: '7', expiredIdentity: null },
  ]);
});

test('supabaseWiring: auth context sync failure does not block downstream runtime apply', async () => {
  const { SupabaseSessionManagerStub, getInstance } = createSupabaseSessionManagerStub();
  const timers = createFakeTimers();
  let reconnectCount = 0;
  let disconnectCount = 0;
  let persistCount = 0;
  let authTokenChangedCount = 0;
  const broadcasts = [];

  const wiring = createSupabaseWiring({
    accountLoginEnabled: true,
    ...ownerCallbacks,
    getLocalConnectionStatus: async () => configuredStatus(wiring.getSessionManager()),
    createClient: () => ({}),
    SupabaseSessionManager: SupabaseSessionManagerStub,
    runtimeConfig: {
      supabase_url: 'https://example.supabase.co',
      supabase_publishable_key: 'sb_publishable_test',
    },
    safeStorage: {},
    userDataDir: '/tmp',
    extractUserIdFromJwt: () => null,
    onAuthStateBroadcast: (state) => {
      broadcasts.push(state);
    },
    onAuthTokenChanged: () => {
      authTokenChangedCount += 1;
    },
    onAuthContextChanged: async ({ userId }) => {
      if (!userId) return;
      throw new Error('sync failed');
    },
    onLoginStatePersist: () => {
      persistCount += 1;
    },
    onOrchestrationDisconnect: () => {
      disconnectCount += 1;
    },
    onOrchestrationReconnect: () => {
      reconnectCount += 1;
    },
    timers: timers.api,
  });

  await wiring.initialize();
  const mgr = getInstance();
  assert.ok(mgr, 'SupabaseSessionManager instance is required');

  mgr.emit({ isLoggedIn: true, user: { id: 'user_a' } }, 'token-a');
  await new Promise((resolve) => setImmediate(resolve));

  assert.equal(reconnectCount, 1);
  assert.equal(disconnectCount, 2);
  assert.equal(persistCount, 2);
  assert.equal(authTokenChangedCount, 1);
  assert.deepStrictEqual(wiring.getRuntimeState(), {
    status: 'degraded',
    message: 'sync failed',
    owner: null,
  });
  assert.deepStrictEqual(broadcasts.at(-1), {
    authStatus: 'authenticated',
    isLoggedIn: true,
    user: { id: 'user_a' },
    runtimeState: { status: 'degraded', message: 'sync failed', owner: null },
  });
  assert.equal(timers.scheduled.length, 1);
});

test('supabaseWiring: degraded runtime retries the same auth context and recovers without a new auth event', async () => {
  const { SupabaseSessionManagerStub, getInstance } = createSupabaseSessionManagerStub();
  const timers = createFakeTimers();
  let reconnectCount = 0;
  let disconnectCount = 0;
  let syncAttemptCount = 0;
  const broadcasts = [];

  const wiring = createSupabaseWiring({
    accountLoginEnabled: true,
    ...ownerCallbacks,
    getLocalConnectionStatus: async () => configuredStatus(wiring.getSessionManager()),
    createClient: () => ({}),
    SupabaseSessionManager: SupabaseSessionManagerStub,
    runtimeConfig: {
      supabase_url: 'https://example.supabase.co',
      supabase_publishable_key: 'sb_publishable_test',
    },
    safeStorage: {},
    userDataDir: '/tmp',
    extractUserIdFromJwt: () => null,
    onAuthStateBroadcast: (state) => {
      broadcasts.push(state);
    },
    onAuthTokenChanged: () => {},
    onAuthContextChanged: async ({ userId }) => {
      if (!userId) return;
      syncAttemptCount += 1;
      if (syncAttemptCount === 1) {
        throw new Error('sync failed');
      }
    },
    onLoginStatePersist: () => {},
    onOrchestrationDisconnect: () => {
      disconnectCount += 1;
    },
    onOrchestrationReconnect: () => {
      reconnectCount += 1;
    },
    timers: timers.api,
  });

  await wiring.initialize();
  const mgr = getInstance();
  assert.ok(mgr, 'SupabaseSessionManager instance is required');

  mgr.emit({ isLoggedIn: true, user: { id: 'user_a' } }, 'token-a', '7');
  await new Promise((resolve) => setImmediate(resolve));

  assert.equal(syncAttemptCount, 1);
  assert.deepStrictEqual(wiring.getRuntimeState(), {
    status: 'degraded',
    message: 'sync failed',
    owner: null,
  });
  assert.equal(timers.scheduled.length, 1);

  await timers.runNext();
  await new Promise((resolve) => setImmediate(resolve));

  assert.equal(syncAttemptCount, 2);
  assert.deepStrictEqual(wiring.getRuntimeState(), {
    status: 'ready',
    message: null,
    owner: { id: 'user_a', kind: 'account' },
  });
  assert.equal(reconnectCount, 2);
  assert.equal(disconnectCount, 2);
  assert.deepStrictEqual(broadcasts.at(-1), {
    authStatus: 'authenticated',
    isLoggedIn: true,
    user: { id: 'user_a' },
    runtimeState: { status: 'ready', message: null, owner: { id: 'user_a', kind: 'account' } },
  });
});

test('subject transition awaits recorder stop before replacing token, scope, or backend auth', async (t) => {
  const { SupabaseSessionManagerStub, getInstance } = createSupabaseSessionManagerStub();
  const calls = []; let releaseStop; let helperUserId = null; let publishedToken = null;
  const { createLocalBackendClient } = require('../electron/dist/localBackend/client.js');
  t.mock.method(globalThis, 'fetch', async (url) => {
    assert.equal(url, 'http://127.0.0.1:61131/v1/agents/users/alice/context-source');
    return new Response('{}');
  });
  const wiring = createSupabaseWiring({
    accountLoginEnabled: true,
    ...ownerCallbacks,
    getLocalConnectionStatus: async () => ({ configured: true, activeOwnerId: helperUserId ?? 'guest-owner', cloudSessionState: helperUserId ? 'present' : 'absent' }),
    createClient: () => ({}), SupabaseSessionManager: SupabaseSessionManagerStub,
    runtimeConfig: { supabase_url: 'https://example.supabase.co', supabase_publishable_key: 'key' },
    safeStorage: {}, userDataDir: '/tmp', extractUserIdFromJwt: () => null, onAuthStateBroadcast: () => {},
    onLoginStatePersist: () => {},
    onAuthTokenChanged: token => { publishedToken = token; },
    onOrchestrationDisconnect: () => {}, onOrchestrationReconnect: () => {},
    beforeOwnerChanged: async () => {
      if (helperUserId !== 'alice') return;
      // The recorder closes its old source through the authenticated local client.
      await client.requestJson({ path: '/v1/agents/users/alice/context-source', method: 'GET' });
      await new Promise(resolve => { calls.push('stop'); releaseStop = resolve; });
    },
    onLocalOwnerChanged: owner => calls.push(`scope:${owner.id}`),
    onAuthContextChanged: async ({ userId }) => { helperUserId = userId; calls.push(`auth:${userId}`); },
  });
  const client = createLocalBackendClient({
    getRuntimeBackendUrl: () => 'http://127.0.0.1:61131',
    getLocalApiToken: () => 'local-token',
    getRuntimeState: wiring.getRuntimeState,
  });
  await wiring.initialize(); const manager = getInstance();
  manager.emit({ isLoggedIn: true, user: { id: 'alice' } }, 'token-a', '1');
  await new Promise(resolve => setImmediate(resolve)); calls.length = 0;
  manager.emit({ isLoggedIn: true, user: { id: 'alice' } }, 'token-a2', '1');
  await new Promise(resolve => setImmediate(resolve));
  assert.deepEqual(calls, ['auth:alice']); calls.length = 0;
  manager.emit({ isLoggedIn: true, user: { id: 'bob' } }, 'token-b', '2');
  await new Promise(resolve => setImmediate(resolve));
  assert.deepEqual(calls, ['stop']); assert.equal(publishedToken, 'token-a2');
  assert.equal(wiring.getLocalOwnerId(), null);
  releaseStop(); await new Promise(resolve => setImmediate(resolve));
  assert.deepEqual(calls, ['stop', 'auth:bob', 'scope:bob']);
  assert.equal(publishedToken, 'token-b');
});

// Supabase refreshes the access token of a live session about every hour and emits the
// same account again. The owner cannot change, so renderers must keep their scope — but
// only while the helper that confirmed that owner is still the one answering for it.
const GUEST_ANSWER = { activeOwnerId: 'guest-owner', cloudSessionState: 'absent' };
const RESTARTED_ANSWER = { helperInstanceId: 'helper-2' };
// Each case lists what `status` answers from the refresh onwards, then the whole
// observable sequence. `owner:none` must be published before a sync can start a helper.
const REFRESH_CASES = {
  unchanged: { answers: [null], events: ['state:ready:user_a', 'auth:token-a2'] },
  gone: {
    answers: ['unavailable', RESTARTED_ANSWER],
    events: [
      'state:ready:none',
      'state:syncing:none',
      'auth:token-a2',
      'connect',
      'state:ready:user_a',
    ],
  },
  'restarted before the sync': {
    answers: [RESTARTED_ANSWER],
    events: [
      'state:ready:none',
      'state:syncing:none',
      'auth:token-a2',
      'connect',
      'state:ready:user_a',
    ],
  },
  'restarted during the sync': {
    answers: [null, RESTARTED_ANSWER],
    events: [
      'state:ready:user_a',
      'auth:token-a2',
      'state:ready:none',
      'disconnect',
      'stop',
      'scope:user_a',
      'connect',
      'state:ready:user_a',
    ],
  },
  'another owner': {
    answers: [GUEST_ANSWER],
    events: [
      'state:ready:none',
      'state:syncing:none',
      'auth:token-a2',
      'scope:guest-owner',
      'connect',
      'state:ready:guest-owner',
    ],
  },
};

for (const [helper, expected] of Object.entries(REFRESH_CASES)) {
  test(`supabaseWiring: a token refresh for the same account keeps the confirmed owner (helper ${helper})`, async () => {
    const { SupabaseSessionManagerStub, getInstance } = createSupabaseSessionManagerStub();
    const events = [];
    let answers = [null];
    let statusCalls = 0;
    const wiring = createSupabaseWiring({
      accountLoginEnabled: true,
      getLocalConnectionStatus: async () => {
        statusCalls += 1;
        const answer = answers.length > 1 ? answers.shift() : answers[0];
        if (answer === 'unavailable') throw new Error('Control socket unavailable.');
        return { ...configuredStatus(wiring.getSessionManager()), ...answer };
      },
      createClient: () => ({}),
      SupabaseSessionManager: SupabaseSessionManagerStub,
      runtimeConfig: null,
      safeStorage: {},
      userDataDir: '/tmp',
      extractUserIdFromJwt: () => null,
      onAuthStateBroadcast: ({ runtimeState }) =>
        events.push(`state:${runtimeState.status}:${runtimeState.owner?.id ?? 'none'}`),
      onAuthContextChanged: async ({ token }) => events.push(`auth:${token}`),
      beforeOwnerChanged: async () => events.push('stop'),
      onLocalOwnerChanged: (owner) => events.push(`scope:${owner.id}`),
      onLoginStatePersist: () => {},
      onOrchestrationDisconnect: () => events.push('disconnect'),
      onOrchestrationReconnect: () => events.push('connect'),
    });

    await wiring.initialize();
    const manager = getInstance();
    manager.emit({ isLoggedIn: true, user: { id: 'user_a' } }, 'token-a', '7');
    await new Promise((resolve) => setImmediate(resolve));
    const account = { id: 'user_a', kind: 'account' };
    assert.deepStrictEqual(wiring.getRuntimeState(), {
      status: 'ready',
      message: null,
      owner: account,
    });
    const heldRuntimeState = wiring.getRuntimeState();
    events.length = 0;
    answers = expected.answers;
    statusCalls = 0;

    manager.emit({ isLoggedIn: true, user: { id: 'user_a' } }, 'token-a2', '7');
    await new Promise((resolve) => setImmediate(resolve));

    assert.deepStrictEqual(events, expected.events);
    assert.deepStrictEqual(wiring.getRuntimeState(), {
      status: 'ready',
      message: null,
      owner: helper === 'another owner' ? { id: 'guest-owner', kind: 'guest' } : account,
    });
    if (helper !== 'unchanged') return;
    // The held owner is confirmed before the sync and again after it.
    assert.equal(statusCalls, 2);
    // A history request in flight compares this object to decide the owner changed.
    assert.strictEqual(wiring.getRuntimeState(), heldRuntimeState);
  });
}

test('supabaseWiring: a superseded owner switch stops before it prepares the stale scope', async () => {
  const { SupabaseSessionManagerStub, getInstance } = createSupabaseSessionManagerStub();
  const events = [];
  let restartDuringSync = false;
  let holdStop = false;
  let releaseStop = () => {};
  const wiring = createSupabaseWiring({
    accountLoginEnabled: true,
    getLocalConnectionStatus: async () => ({
      ...configuredStatus(wiring.getSessionManager()),
      // The helper is still there when the apply starts and gone by the time it syncs.
      helperInstanceId: restartDuringSync ? 'helper-2' : 'helper-1',
    }),
    createClient: () => ({}), SupabaseSessionManager: SupabaseSessionManagerStub, runtimeConfig: null,
    safeStorage: {}, userDataDir: '/tmp', extractUserIdFromJwt: () => null, onAuthStateBroadcast: () => {},
    onAuthContextChanged: async ({ userId }) => {
      events.push(`auth:${userId}`);
      if (holdStop) restartDuringSync = true;
    },
    beforeOwnerChanged: async () => {
      events.push('stop');
      if (holdStop) await new Promise((resolve) => { releaseStop = resolve; });
    },
    onLocalOwnerChanged: (owner) => events.push(`scope:${owner.id}`),
    onLoginStatePersist: () => {},
    onOrchestrationDisconnect: () => {}, onOrchestrationReconnect: () => {},
  });

  await wiring.initialize();
  const manager = getInstance();
  manager.emit({ isLoggedIn: true, user: { id: 'user_a' } }, 'token-a', '7');
  await new Promise((resolve) => setImmediate(resolve));
  events.length = 0;

  // The refresh keeps the owner, then finds a restarted helper after its context sync
  // and holds in the recorder stop that the switch triggers.
  holdStop = true;
  manager.emit({ isLoggedIn: true, user: { id: 'user_a' } }, 'token-a2', '7');
  await new Promise((resolve) => setImmediate(resolve));
  assert.deepStrictEqual(events, ['auth:user_a', 'stop']);

  manager.emit({ isLoggedIn: true, user: { id: 'user_b' } }, 'token-b', '8');
  await new Promise((resolve) => setImmediate(resolve));
  releaseStop();
  await new Promise((resolve) => setImmediate(resolve));

  // The superseded apply must not prepare user_a's scope on top of user_b's login.
  assert.deepStrictEqual(events, ['auth:user_a', 'stop', 'auth:user_b', 'scope:user_b']);
  assert.equal(wiring.getLocalOwnerId(), 'user_b');
});

test('supabaseWiring: a signed-out startup still configures the local backend once', async () => {
  const events = [];
  let reconnectCount = 0;
  let disconnectCount = 0;
  const { SupabaseSessionManagerStub } = createSupabaseSessionManagerStub();

  const wiring = createSupabaseWiring({
    accountLoginEnabled: true,
    ...ownerCallbacks,
    getLocalConnectionStatus: async () => configuredStatus(wiring.getSessionManager()),
    createClient: () => ({}),
    SupabaseSessionManager: SupabaseSessionManagerStub,
    runtimeConfig: {
      supabase_url: 'https://example.supabase.co',
      supabase_publishable_key: 'sb_publishable_test',
    },
    safeStorage: {},
    userDataDir: '/tmp',
    extractUserIdFromJwt: () => null,
    onAuthStateBroadcast: () => {},
    onAuthContextChanged: async (payload) => {
      events.push(payload);
    },
    onLoginStatePersist: () => {},
    onOrchestrationDisconnect: () => {
      disconnectCount += 1;
    },
    onOrchestrationReconnect: () => {
      reconnectCount += 1;
    },
  });

  await wiring.initialize();

  assert.deepStrictEqual(events, [
    { token: null, userId: null, sessionVersion: null, expiredIdentity: null },
  ]);
  // The local API answers the helper's owner without a cloud session, so the
  // runtime and orchestration socket both use the confirmed guest owner.
  assert.deepStrictEqual(wiring.getRuntimeState(), { status: 'ready', message: null, owner: { id: 'guest-owner', kind: 'guest' } });
  assert.equal(reconnectCount, 1);
  assert.equal(disconnectCount, 0);
});

test('supabaseWiring: signing out of an expired session still reaches the local backend', async () => {
  const events = [];
  const { SupabaseSessionManagerStub, getInstance } = createSupabaseSessionManagerStub();
  let expiredIdentity = null;

  const wiring = createSupabaseWiring({
    accountLoginEnabled: true,
    ...ownerCallbacks,
    getLocalConnectionStatus: async () => configuredStatus(wiring.getSessionManager()),
    createClient: () => ({}),
    SupabaseSessionManager: SupabaseSessionManagerStub,
    runtimeConfig: {
      supabase_url: 'https://example.supabase.co',
      supabase_publishable_key: 'sb_publishable_test',
    },
    safeStorage: {},
    userDataDir: '/tmp',
    extractUserIdFromJwt: () => null,
    onAuthStateBroadcast: () => {},
    onAuthContextChanged: async (payload) => {
      events.push(payload);
    },
    onLoginStatePersist: () => {},
    onOrchestrationDisconnect: () => {},
    onOrchestrationReconnect: () => {},
  });

  await wiring.initialize();
  const mgr = getInstance();
  mgr.getExpiredCloudIdentity = () => expiredIdentity;

  expiredIdentity = { userId: 'user_a', sessionVersion: '4' };
  mgr.emit({ authStatus: 'expired', isLoggedIn: false, user: null }, null);
  await new Promise((resolve) => setImmediate(resolve));

  expiredIdentity = null;
  mgr.emit({ authStatus: 'unauthenticated', isLoggedIn: false, user: null }, null);
  await new Promise((resolve) => setImmediate(resolve));

  assert.deepStrictEqual(
    events.map((event) => event.expiredIdentity),
    [null, { userId: 'user_a', sessionVersion: '4' }, null]
  );
});

test('supabaseWiring: a failed expired sync is retried by the next signed-out transition', async () => {
  const events = [];
  const { SupabaseSessionManagerStub, getInstance } = createSupabaseSessionManagerStub();
  const timers = createFakeTimers();
  let expiredIdentity = null;

  const wiring = createSupabaseWiring({
    accountLoginEnabled: true,
    ...ownerCallbacks,
    getLocalConnectionStatus: async () => configuredStatus(wiring.getSessionManager()),
    createClient: () => ({}),
    SupabaseSessionManager: SupabaseSessionManagerStub,
    runtimeConfig: {
      supabase_url: 'https://example.supabase.co',
      supabase_publishable_key: 'sb_publishable_test',
    },
    safeStorage: {},
    userDataDir: '/tmp',
    extractUserIdFromJwt: () => null,
    onAuthStateBroadcast: () => {},
    onAuthContextChanged: async (payload) => {
      events.push(payload);
      if (payload.expiredIdentity) throw new Error('sync failed');
    },
    onLoginStatePersist: () => {},
    onOrchestrationDisconnect: () => {},
    onOrchestrationReconnect: () => {},
    timers: timers.api,
  });

  await wiring.initialize();
  const mgr = getInstance();
  mgr.getExpiredCloudIdentity = () => expiredIdentity;

  expiredIdentity = { userId: 'user_a', sessionVersion: '4' };
  mgr.emit({ authStatus: 'expired', isLoggedIn: false, user: null }, null);
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(wiring.getRuntimeState().status, 'degraded');

  // Signing out of the failed expiry still reaches the helper.
  expiredIdentity = null;
  mgr.emit({ authStatus: 'unauthenticated', isLoggedIn: false, user: null }, null);
  await new Promise((resolve) => setImmediate(resolve));

  assert.deepStrictEqual(
    events.map((event) => event.expiredIdentity),
    [null, { userId: 'user_a', sessionVersion: '4' }, null]
  );
  assert.equal(wiring.getRuntimeState().status, 'ready');
});


for (const trigger of ['idle', 'during_apply', 'failed_signout']) {
  test(`supabaseWiring: runtime auth recovers without an auth event (${trigger})`, async () => {
    const { SupabaseSessionManagerStub, getInstance } = createSupabaseSessionManagerStub();
    const timers = createFakeTimers();
    const events = [];
    const broadcasts = [];
    let reportDuringApply = false;
    const wiring = createSupabaseWiring({
      accountLoginEnabled: true,
      ...ownerCallbacks,
      clearForSignOut: async () => {
        events.push(['helper-session-cleared']);
        return { contained: true };
      },
      getLocalConnectionStatus: async () => configuredStatus(wiring.getSessionManager()),
      createClient: () => ({}),
      SupabaseSessionManager: SupabaseSessionManagerStub,
      runtimeConfig: {
        supabase_url: 'https://example.supabase.co',
        supabase_publishable_key: 'sb_publishable_test',
      },
      safeStorage: {},
      userDataDir: '/tmp',
      extractUserIdFromJwt: () => null,
      onAuthStateBroadcast: (state) => broadcasts.push(state),
      onAuthContextChanged: async (payload) => {
        events.push(['configure', payload]);
        if (reportDuringApply) {
          reportDuringApply = false;
          wiring.reportRuntimeUnavailable();
        }
      },
      onLoginStatePersist: () => {},
      onOrchestrationDisconnect: () => events.push(['disconnect']),
      onOrchestrationReconnect: () => events.push(['connect']),
      timers: timers.api,
    });
    await wiring.initialize();
    reportDuringApply = trigger === 'during_apply';
    getInstance().emit({ isLoggedIn: true, user: { id: 'user_a' } }, 'token-a', '7');
    await new Promise((resolve) => setImmediate(resolve));
    if (trigger === 'idle') wiring.reportRuntimeUnavailable();
    if (trigger === 'failed_signout') {
      const { buildMainContext } = require('../electron/dist/ipc/mainContextFactory.js');
      const { CredentialStorageError } = require('../electron/dist/auth/encryptedJsonFile.js');
      const mgr = getInstance();
      mgr.signOut = async () => { throw new CredentialStorageError('delete_failed'); };
      const context = buildMainContext({
        isDevRuntime: () => false,
        frontendDistIndex: '/tmp/index.html',
        getSupabaseSessionManager: () => mgr,
        signOut: wiring.signOut,
      });
      assert.equal((await context.auth.signOut()).ok, false);
      assert.equal(mgr.getState().isLoggedIn, true);
      assert.ok(events.some(([event]) => event === 'helper-session-cleared'));
    }
    await new Promise((resolve) => setImmediate(resolve));

    assert.equal(wiring.getRuntimeState().status, 'degraded');
    assert.equal(broadcasts.at(-1).runtimeState.status, 'degraded');
    assert.deepStrictEqual(events.at(-1), ['disconnect']);
    events.length = 0;
    assert.equal(timers.scheduled.length, 1);
    await timers.runNext();
    await new Promise((resolve) => setImmediate(resolve));

    assert.equal(wiring.getRuntimeState().status, 'ready');
    assert.equal(broadcasts.at(-1).runtimeState.status, 'ready');
    assert.deepStrictEqual(events, [
      ['configure', { token: 'token-a', userId: 'user_a', sessionVersion: '7', expiredIdentity: null }],
      ['connect'],
    ]);
    assert.equal(timers.scheduled.length, 0);
  });
}

test('local owner is unavailable until configure and status finish, including later transitions', async () => {
  const { SupabaseSessionManagerStub, getInstance } = createSupabaseSessionManagerStub();
  let finishConfigure;
  let finishStatus;
  let holdConfigure = true;
  let holdStatus = true;
  let activeOwnerId = 'guest-owner';
  let cloudSessionState = 'absent';
  const broadcasts = [];
  const { buildMainContext } = require('../electron/dist/ipc/mainContextFactory.js');
  const { broadcastAuthStateToAllWindows } = require('../electron/dist/auth/authBroadcast.js');
  const window = { isDestroyed: () => false, webContents: { send: (channel, payload) => {
    assert.equal(channel, 'auth:stateChanged');
    broadcasts.push(payload);
  } } };
  const wiring = createSupabaseWiring({
    accountLoginEnabled: true,
    ...ownerCallbacks,
    createClient: () => ({}), SupabaseSessionManager: SupabaseSessionManagerStub, runtimeConfig: null,
    safeStorage: {}, userDataDir: '/tmp', extractUserIdFromJwt: () => null,
    onAuthStateBroadcast: state => broadcastAuthStateToAllWindows([window], state),
    onAuthContextChanged: async ({ userId, expiredIdentity }) => {
      if (holdConfigure) await new Promise(resolve => { finishConfigure = resolve; });
      activeOwnerId = userId ?? expiredIdentity?.userId ?? 'guest-owner';
      cloudSessionState = userId ? 'present' : expiredIdentity ? 'expired' : 'absent';
    },
    getLocalConnectionStatus: async () => {
      if (holdStatus) await new Promise(resolve => { finishStatus = resolve; });
      return { configured: true, activeOwnerId, cloudSessionState };
    },
    onLoginStatePersist: () => {},
    onOrchestrationDisconnect: () => {}, onOrchestrationReconnect: () => {},
  });
  const context = buildMainContext({
    isDevRuntime: () => false, frontendDistIndex: '/tmp/index.html',
    getRuntimeState: wiring.getRuntimeState,
    getSupabaseSessionManager: wiring.getSessionManager,
    getSupabaseSessionInitializationStatus: wiring.getInitializationStatus,
  });
  const initializing = wiring.initialize();
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(wiring.getRuntimeState().status, 'syncing');
  assert.equal(wiring.getLocalOwnerId(), null);
  assert.equal(context.auth.getState().runtimeState.owner, null);
  assert.equal(broadcasts.at(-1).runtimeState.owner, null);
  finishConfigure();
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(wiring.getRuntimeState().status, 'syncing');
  assert.equal(wiring.getLocalOwnerId(), null);
  assert.equal(context.auth.getState().runtimeState.owner, null);
  assert.equal(broadcasts.at(-1).runtimeState.owner, null);
  finishStatus();
  await initializing;
  assert.equal(wiring.getLocalOwnerId(), 'guest-owner');
  assert.deepEqual(broadcasts.at(-1).runtimeState.owner, { id: 'guest-owner', kind: 'guest' });
  assert.deepEqual(context.auth.getState(), broadcasts.at(-1));
  assert.equal(broadcasts.at(-1).user, null);
  assert.equal(broadcasts.at(-1).authStatus, 'unauthenticated');

  holdConfigure = false;
  const manager = getInstance();
  manager.emit({ authStatus: 'authenticated', isLoggedIn: true, user: { id: 'account-a' } }, 'token-a', '1');
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(wiring.getRuntimeState().status, 'syncing');
  assert.equal(wiring.getLocalOwnerId(), null);
  assert.equal(context.auth.getState().runtimeState.owner, null);
  assert.equal(broadcasts.at(-1).runtimeState.owner, null);
  finishStatus();
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(wiring.getLocalOwnerId(), 'account-a');
  assert.deepEqual(broadcasts.at(-1).runtimeState.owner, { id: 'account-a', kind: 'account' });
  assert.deepEqual(context.auth.getState(), broadcasts.at(-1));

  holdStatus = false;
  manager.getExpiredCloudIdentity = () => ({ userId: 'account-a', sessionVersion: '1' });
  manager.emit({ authStatus: 'expired', isLoggedIn: false, user: null }, null);
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(wiring.getLocalOwnerId(), 'account-a');
  assert.deepEqual(broadcasts.at(-1).runtimeState.owner, { id: 'account-a', kind: 'account' });
  assert.deepEqual(context.auth.getState(), broadcasts.at(-1));
  assert.equal(broadcasts.at(-1).user, null);
  assert.equal(broadcasts.at(-1).authStatus, 'expired');

  manager.getExpiredCloudIdentity = () => null;
  manager.emit({ authStatus: 'unauthenticated', isLoggedIn: false, user: null }, null);
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(wiring.getLocalOwnerId(), 'guest-owner');
  assert.deepEqual(broadcasts.at(-1).runtimeState.owner, { id: 'guest-owner', kind: 'guest' });
  assert.deepEqual(context.auth.getState(), broadcasts.at(-1));
});

for (const failure of ['unconfigured', 'status_error']) {
  test(`local owner stays unavailable on ${failure} and recovers through the runtime retry`, async () => {
    const { SupabaseSessionManagerStub, getInstance } = createSupabaseSessionManagerStub();
    const timers = createFakeTimers();
    const broadcasts = [];
    let statusFails = true;
    const wiring = createSupabaseWiring({
      accountLoginEnabled: true,
      ...ownerCallbacks,
      createClient: () => ({}), SupabaseSessionManager: SupabaseSessionManagerStub, runtimeConfig: null,
      safeStorage: {}, userDataDir: '/tmp', extractUserIdFromJwt: () => null,
      onAuthStateBroadcast: state => broadcasts.push(state),
      onAuthContextChanged: async () => {},
      getLocalConnectionStatus: async () => {
        if (statusFails && failure === 'status_error') throw new Error('Control socket unavailable.');
        return { configured: !statusFails, activeOwnerId: 'guest-owner', cloudSessionState: 'absent' };
      },
      onLoginStatePersist: () => {},
      onOrchestrationDisconnect: () => {}, onOrchestrationReconnect: () => {},
      timers: timers.api,
    });
    await wiring.initialize();
    assert.equal(wiring.getRuntimeState().status, 'degraded');
    assert.equal(wiring.getLocalOwnerId(), null);
    assert.equal(broadcasts.at(-1).runtimeState.status, 'degraded');
    assert.equal(timers.scheduled.length, 1);

    statusFails = false;
    await timers.runNext();
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(wiring.getLocalOwnerId(), 'guest-owner');
    assert.equal(broadcasts.at(-1).runtimeState.status, 'ready');
    assert.equal(timers.scheduled.length, 0);

    // A repeated cloud state still rechecks a helper that has restarted or failed.
    statusFails = true;
    getInstance().emit({ isLoggedIn: false, user: null }, null);
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(wiring.getRuntimeState().status, 'degraded');
    assert.equal(wiring.getLocalOwnerId(), null);
    assert.equal(timers.scheduled.length, 1);
  });
}
