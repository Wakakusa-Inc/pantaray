const assert = require('node:assert/strict');
const { test } = require('node:test');
const { createSupabaseWiring } = require('../electron/dist/auth/supabaseWiring.js');

const tick = () => new Promise(resolve => setImmediate(resolve));
function deferred() {
  let resolve;
  const promise = new Promise(done => { resolve = done; });
  return { promise, resolve };
}
const signedOut = { authStatus: 'unauthenticated', isLoggedIn: false, user: null };
const account = id => ({ authStatus: 'authenticated', isLoggedIn: true, user: { id } });

function setup({ apply = async () => {}, status = async value => value, beforeOwnerChanged = async () => {}, prepare = () => {}, timers } = {}) {
  class SessionManager {
    static instance;
    constructor() {
      SessionManager.instance = this;
      this.state = signedOut;
      this.token = null;
      this.version = null;
      this.expired = null;
      this.listeners = [];
    }
    async initialize() {}
    getState() { return this.state; }
    getAccessToken() { return this.token; }
    getDesktopSessionVersion() { return this.version; }
    getExpiredCloudIdentity() { return this.expired; }
    onStateChanged(listener) { this.listeners.push(listener); }
    emit(state, token = null, version = null, expired = null) {
      Object.assign(this, { state, token, version, expired });
      for (const listener of this.listeners) listener(state);
    }
  }
  const sent = [];
  const broadcasts = [];
  let helper = { configured: true, activeOwnerId: 'guest', cloudSessionState: 'absent' };
  const wiring = createSupabaseWiring({
    accountLoginEnabled: true,
    createClient: () => ({}), SupabaseSessionManager: SessionManager,
    runtimeConfig: null, safeStorage: {}, userDataDir: '/tmp',
    extractUserIdFromJwt: () => null,
    beforeOwnerChanged,
    onLocalOwnerChanged: prepare,
    timers,
    onAuthStateBroadcast: value => broadcasts.push(value),
    onAuthContextChanged: async context => {
      sent.push(context);
      await apply(context);
      helper = {
        configured: true,
        activeOwnerId: context.userId ?? context.expiredIdentity?.userId ?? 'guest',
        cloudSessionState: context.userId ? 'present' : context.expiredIdentity ? 'expired' : 'absent',
      };
    },
    getLocalConnectionStatus: () => status(helper),
    onLoginStatePersist: () => {},
    onOrchestrationDisconnect: () => {}, onOrchestrationReconnect: () => {},
  });
  return { wiring, sent, broadcasts, manager: () => SessionManager.instance, helper: () => helper };
}

test('login arriving during startup configure reaches the helper and publishes only the latest owner', async () => {
  const startup = deferred();
  const fixture = setup({ apply: context => context.userId ? undefined : startup.promise });
  const initialized = fixture.wiring.initialize();
  await tick();
  fixture.manager().emit(account('alice'), 'token-1', '1');
  startup.resolve();
  await initialized;
  await tick();
  assert.equal(fixture.helper().activeOwnerId, 'alice');
  assert.equal(fixture.wiring.getLocalOwnerId(), 'alice');
  assert.deepEqual(fixture.broadcasts.filter(state => state.runtimeState.status === 'ready' && state.runtimeState.owner)
    .map(state => state.runtimeState.owner.id), ['alice']);
});

for (const next of [account('bob'), signedOut]) {
  test(`publishes owner invalidation while recorder cleanup waits for ${next.authStatus}`, async () => {
    const stopped = deferred();
    let holdStop = false;
    const fixture = setup({ beforeOwnerChanged: () => holdStop ? stopped.promise : Promise.resolve() });
    await fixture.wiring.initialize();
    fixture.manager().emit(account('alice'), 'token-a', '1'); await tick();
    holdStop = true;
    fixture.manager().emit(next, next.user ? 'token-b' : null, next.user ? '2' : null);
    await tick();
    try {
      assert.equal(fixture.wiring.getLocalOwnerId(), null);
      assert.deepEqual(fixture.broadcasts.at(-1).runtimeState, {
        status: 'ready', message: null, owner: null,
      });
      // Cleanup still belongs to alice; no helper switch may precede its stop.
      assert.equal(fixture.helper().activeOwnerId, 'alice');
    } finally {
      stopped.resolve();
      await tick();
    }
    assert.equal(fixture.wiring.getLocalOwnerId(), next.user?.id ?? 'guest');
  });
}

test('rapid refreshes never pair an older access token with a newer session version', async () => {
  const fixture = setup();
  await fixture.wiring.initialize();
  const manager = fixture.manager();
  manager.emit(account('alice'), 'token-1', '1');
  manager.emit(account('alice'), 'token-2', '2');
  await tick();
  for (const context of fixture.sent.filter(context => context.token)) {
    assert.equal(context.token, `token-${context.sessionVersion}`);
  }
  assert.equal(fixture.sent.at(-1).token, 'token-2');
  // A version change alone must still update the helper's session identity.
  manager.emit(account('alice'), 'token-2', '3');
  await tick();
  assert.equal(fixture.sent.at(-1).sessionVersion, '3');
});

for (const boundary of ['apply', 'status']) {
  test(`an obsolete ${boundary} response cannot publish an owner, and returning to the previous account resyncs`, async () => {
    const blocked = deferred();
    let hold = false;
    const fixture = setup({
      beforeOwnerChanged: async () => {
        // Cleanup uses HTTP that is available only while the old runtime is ready.
        assert.equal(fixture.wiring.getRuntimeState().status, 'ready');
      },
      apply: context => boundary === 'apply' && hold && context.userId === 'bob'
        ? blocked.promise : undefined,
      status: async value => {
        if (boundary === 'status' && hold && value.activeOwnerId === 'bob') await blocked.promise;
        return value;
      },
    });
    await fixture.wiring.initialize();
    const manager = fixture.manager();
    manager.emit(account('alice'), 'token-a', '1');
    await tick();
    fixture.broadcasts.length = 0;
    hold = true;
    manager.emit(account('bob'), 'token-b', '2');
    await tick();
    manager.emit(account('alice'), 'token-a', '1');
    blocked.resolve();
    await tick();
    assert.deepEqual(fixture.sent.map(context => context.userId), [null, 'alice', 'bob', 'alice']);
    assert.equal(fixture.helper().activeOwnerId, 'alice');
    assert.equal(fixture.wiring.getLocalOwnerId(), 'alice');
    assert.deepEqual(fixture.broadcasts.filter(state => state.runtimeState.status === 'ready' && state.runtimeState.owner)
      .map(state => state.runtimeState.owner.id), ['alice']);
  });
}

test('expiry identity is captured before a subsequent sign-out clears the manager', async () => {
  const blocked = deferred();
  const fixture = setup({ apply: context => context.expiredIdentity ? blocked.promise : undefined });
  await fixture.wiring.initialize();
  const manager = fixture.manager();
  manager.emit(account('alice'), 'token-a', '1');
  await tick();
  fixture.broadcasts.length = 0;
  const identity = { userId: 'alice', sessionVersion: '1' };
  manager.emit({ authStatus: 'expired', isLoggedIn: false, user: null }, null, null, identity);
  await tick();
  manager.emit(signedOut);
  blocked.resolve();
  await tick();
  assert.deepEqual(fixture.sent.find(context => context.expiredIdentity)?.expiredIdentity,
    { userId: 'alice', sessionVersion: '1' });
  assert.deepEqual(fixture.broadcasts.filter(state => state.runtimeState.status === 'ready' && state.runtimeState.owner)
    .map(state => state.authStatus), ['unauthenticated']);
  assert.equal(fixture.helper().cloudSessionState, 'absent');
  assert.equal(fixture.wiring.getLocalOwnerId(), 'guest');
});

test('owner preparation and recorder cleanup follow local identity, including guest and expired sessions', async () => {
  const prepared = [];
  const stopped = [];
  const fixture = setup({
    prepare: owner => {
      assert.equal(fixture.wiring.getLocalOwnerId(), null);
      prepared.push(owner);
    },
    beforeOwnerChanged: async () => stopped.push(fixture.helper().activeOwnerId),
  });
  await fixture.wiring.initialize();
  const manager = fixture.manager();
  manager.emit(account('alice'), 'token-a', '1'); await tick();
  manager.emit(account('alice'), 'token-a2', '1'); await tick();
  manager.emit({ authStatus: 'expired', isLoggedIn: false, user: null }, null, null,
    { userId: 'alice', sessionVersion: '1' }); await tick();
  assert.equal(fixture.wiring.getLocalOwnerId(), 'alice');
  assert.deepEqual(stopped, ['guest']);
  assert.deepEqual(prepared, [{ id: 'guest', kind: 'guest' }, { id: 'alice', kind: 'account' }]);
  manager.emit(signedOut); await tick();
  manager.emit(account('bob'), 'token-b', '2'); await tick();
  assert.deepEqual(stopped, ['guest', 'alice', 'guest']);
  assert.deepEqual(prepared, [
    { id: 'guest', kind: 'guest' }, { id: 'alice', kind: 'account' },
    { id: 'guest', kind: 'guest' }, { id: 'bob', kind: 'account' },
  ]);
});

test('partial feature preparation is not published and returning to the old owner prepares its scope again', async () => {
  const prepared = [];
  let retry;
  const fixture = setup({
    prepare: owner => {
      prepared.push(owner.id);
      if (owner.id === 'bob') throw new Error('settings read failed');
    },
    timers: { setTimeout: callback => { retry = callback; return callback; }, clearTimeout: () => { retry = null; } },
  });
  await fixture.wiring.initialize();
  const manager = fixture.manager();
  manager.emit(account('alice'), 'token-a', '1'); await tick();
  manager.emit(account('bob'), 'token-b', '2'); await tick();
  assert.equal(fixture.helper().activeOwnerId, 'bob');
  assert.equal(fixture.wiring.getLocalOwnerId(), null);
  assert.equal(fixture.broadcasts.at(-1).runtimeState.status, 'degraded');
  assert.equal(typeof retry, 'function');
  manager.emit(account('alice'), 'token-a', '1'); await tick();
  assert.deepEqual(prepared, ['guest', 'alice', 'bob', 'alice']);
  assert.equal(fixture.wiring.getLocalOwnerId(), 'alice');
  assert.equal(retry, null);
});

test('returning to the previous owner rebinds scopes after a failed transition cleanup', async () => {
  const prepared = [];
  let failCleanup = false;
  let retry;
  const fixture = setup({
    prepare: owner => prepared.push(owner.id),
    beforeOwnerChanged: async () => {
      if (failCleanup) throw new Error('recorder stop failed');
    },
    timers: { setTimeout: callback => { retry = callback; return callback; }, clearTimeout: () => { retry = null; } },
  });
  await fixture.wiring.initialize();
  fixture.manager().emit(account('alice'), 'token-a', '1'); await tick();
  failCleanup = true;
  fixture.manager().emit(account('bob'), 'token-b', '2'); await tick();
  assert.equal(fixture.wiring.getLocalOwnerId(), null);
  assert.equal(fixture.sent.at(-1).userId, 'alice');
  failCleanup = false;
  fixture.manager().emit(account('alice'), 'token-a', '1'); await tick();
  assert.equal(fixture.wiring.getLocalOwnerId(), 'alice');
  assert.deepEqual(prepared, ['guest', 'alice', 'alice']);
  assert.equal(retry, null);
});
