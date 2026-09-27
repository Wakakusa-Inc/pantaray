const assert = require('assert');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { test } = require('node:test');

const { SupabaseSessionManager } = require('../electron/supabase_session_manager');

function createTempDir() {
  return fs.mkdtempSync(path.join(os.tmpdir(), 'pantaray-electron-test-'));
}

function createSafeStorageStub() {
  return {
    isEncryptionAvailable: () => true,
    encryptString: (plain) => {
      const buf = Buffer.from(String(plain), 'utf8');
      // XOR で疑似暗号化（テスト用・可逆）
      for (let i = 0; i < buf.length; i += 1) {
        buf[i] = buf[i] ^ 0xaa;
      }
      return buf;
    },
    decryptString: (buf) => {
      const b = Buffer.from(buf);
      for (let i = 0; i < b.length; i += 1) {
        b[i] = b[i] ^ 0xaa;
      }
      return b.toString('utf8');
    },
  };
}

function createSupabaseClientStub() {
  /** @type {((event: string, session: any) => void) | null} */
  let onAuth = null;
  const calls = {
    setSession: [],
    signOut: 0,
  };

  const client = {
    auth: {
      setSession: async (tokens) => {
        calls.setSession.push(tokens);
        if (typeof onAuth === 'function') {
          onAuth('SIGNED_IN', { user: { id: 'U1', email: 'u1@example.com' }, ...tokens });
        }
        return { error: null };
      },
      onAuthStateChange: (cb) => {
        onAuth = cb;
        return { data: { subscription: { unsubscribe: () => {} } } };
      },
      signOut: async () => {
        calls.signOut += 1;
        if (typeof onAuth === 'function') {
          onAuth('SIGNED_OUT', null);
        }
        return { error: null };
      },
    },
  };

  return { client, calls };
}

function createSupabaseClientStubWithSetSessionFailure() {
  return {
    client: {
      auth: {
        setSession: async () => ({ error: new Error('temporary restore failure') }),
        onAuthStateChange: () => ({ data: { subscription: { unsubscribe: () => {} } } }),
        signOut: async () => ({ error: null }),
      },
    },
  };
}

test('SupabaseSessionManager: applySessionTokens persists encrypted session to disk', async () => {
  const dir = createTempDir();
  const safeStorage = createSafeStorageStub();
  const { client } = createSupabaseClientStub();
  const createClient = () => client;

  const mgr = new SupabaseSessionManager({
    createClient,
    supabaseUrl: 'https://example.supabase.co',
    supabaseAnonKey: 'eyJ.test.test',
    userDataDir: dir,
    safeStorage,
    logger: { warn: () => {}, error: () => {}, debug: () => {}, info: () => {} },
  });

  await mgr.initialize();
  const accessToken = 'access-token-123';
  const refreshToken = 'refresh-token-456';
  const res = await mgr.applySessionTokens({
    access_token: accessToken,
    refresh_token: refreshToken,
    desktop_session_version: '1',
  });
  assert.equal(res.ok, true);

  const p = path.join(dir, 'supabase-session.enc.json');
  assert.equal(fs.existsSync(p), true);

  const raw = fs.readFileSync(p, 'utf8');
  // 平文 token が含まれないこと（暗号化されていること）
  assert.equal(raw.includes(accessToken), false);
  assert.equal(raw.includes(refreshToken), false);
});

test('SupabaseSessionManager: restores session from disk on initialize', async () => {
  const dir = createTempDir();
  const safeStorage = createSafeStorageStub();

  // 1st manager: persist
  {
    const { client } = createSupabaseClientStub();
    const mgr = new SupabaseSessionManager({
      createClient: () => client,
      supabaseUrl: 'https://example.supabase.co',
      supabaseAnonKey: 'eyJ.test.test',
      userDataDir: dir,
      safeStorage,
      logger: { warn: () => {}, error: () => {}, debug: () => {}, info: () => {} },
    });
    await mgr.initialize();
    await mgr.applySessionTokens({
      access_token: 'A',
      refresh_token: 'R',
      desktop_session_version: '1',
    });
  }

  // 2nd manager: restore
  const { client: client2, calls } = createSupabaseClientStub();
  const mgr2 = new SupabaseSessionManager({
    createClient: () => client2,
    supabaseUrl: 'https://example.supabase.co',
    supabaseAnonKey: 'eyJ.test.test',
    userDataDir: dir,
    safeStorage,
    logger: { warn: () => {}, error: () => {}, debug: () => {}, info: () => {} },
  });
  await mgr2.initialize();

  // initialize 内の restore により setSession が呼ばれる
  assert.ok(calls.setSession.length >= 1);
  const last = calls.setSession[calls.setSession.length - 1];
  assert.equal(last.access_token, 'A');
  assert.equal(last.refresh_token, 'R');
  assert.equal(mgr2.getDesktopSessionVersion(), '1');
});

test('SupabaseSessionManager: restore failure preserves persisted session for next launch', async () => {
  const dir = createTempDir();
  const safeStorage = createSafeStorageStub();

  {
    const { client } = createSupabaseClientStub();
    const mgr = new SupabaseSessionManager({
      createClient: () => client,
      supabaseUrl: 'https://example.supabase.co',
      supabaseAnonKey: 'eyJ.test.test',
      userDataDir: dir,
      safeStorage,
      logger: { warn: () => {}, error: () => {}, debug: () => {}, info: () => {} },
    });
    await mgr.initialize();
    await mgr.applySessionTokens({
      access_token: 'A',
      refresh_token: 'R',
      desktop_session_version: '1',
    });
  }

  const sessionPath = path.join(dir, 'supabase-session.enc.json');
  assert.equal(fs.existsSync(sessionPath), true);

  const { client } = createSupabaseClientStubWithSetSessionFailure();
  const mgr = new SupabaseSessionManager({
    createClient: () => client,
    supabaseUrl: 'https://example.supabase.co',
    supabaseAnonKey: 'eyJ.test.test',
    userDataDir: dir,
    safeStorage,
    logger: { warn: () => {}, error: () => {}, debug: () => {}, info: () => {} },
  });

  await mgr.initialize();

  assert.equal(fs.existsSync(sessionPath), true);
  assert.equal(mgr.getAccessToken(), null);
  assert.equal(mgr.getDesktopSessionVersion(), null);
});

test('SupabaseSessionManager: state listeners observe desktop session version during apply', async () => {
  const dir = createTempDir();
  const safeStorage = createSafeStorageStub();
  const { client } = createSupabaseClientStub();
  const mgr = new SupabaseSessionManager({
    createClient: () => client,
    supabaseUrl: 'https://example.supabase.co',
    supabaseAnonKey: 'eyJ.test.test',
    userDataDir: dir,
    safeStorage,
    logger: { warn: () => {}, error: () => {}, debug: () => {}, info: () => {} },
  });

  const observedSessionVersions = [];
  mgr.onStateChanged(() => {
    observedSessionVersions.push(mgr.getDesktopSessionVersion());
  });

  await mgr.initialize();
  const res = await mgr.applySessionTokens({
    access_token: 'A',
    refresh_token: 'R',
    desktop_session_version: '7',
  });

  assert.equal(res.ok, true);
  assert.ok(observedSessionVersions.includes('7'));
});

test('SupabaseSessionManager: signOut removes persisted session file', async () => {
  const dir = createTempDir();
  const safeStorage = createSafeStorageStub();
  const { client } = createSupabaseClientStub();

  const mgr = new SupabaseSessionManager({
    createClient: () => client,
    supabaseUrl: 'https://example.supabase.co',
    supabaseAnonKey: 'eyJ.test.test',
    userDataDir: dir,
    safeStorage,
    logger: { warn: () => {}, error: () => {}, debug: () => {}, info: () => {} },
  });
  await mgr.initialize();
  await mgr.applySessionTokens({
    access_token: 'A',
    refresh_token: 'R',
    desktop_session_version: '1',
  });

  const p = path.join(dir, 'supabase-session.enc.json');
  assert.equal(fs.existsSync(p), true);

  await mgr.signOut();
  assert.equal(fs.existsSync(p), false);
});


function createSupabaseClientStubWithManualEvents() {
  let onAuth = null;
  return {
    emit: (event, session) => onAuth?.(event, session),
    client: {
      auth: {
        setSession: async (tokens) => {
          onAuth?.('SIGNED_IN', { user: { id: 'U1', email: 'u1@example.com' }, ...tokens });
          return { error: null };
        },
        onAuthStateChange: (cb) => {
          onAuth = cb;
          return { data: { subscription: { unsubscribe: () => {} } } };
        },
        signOut: async () => {
          onAuth?.('SIGNED_OUT', null);
          return { error: null };
        },
      },
    },
  };
}

test('SupabaseSessionManager: a SIGNED_OUT the app did not request is an expiry that keeps the identity', async () => {
  const dir = createTempDir();
  const { client, emit } = createSupabaseClientStubWithManualEvents();
  const mgr = new SupabaseSessionManager({
    createClient: () => client,
    supabaseUrl: 'https://example.supabase.co',
    supabaseAnonKey: 'eyJ.test.test',
    userDataDir: dir,
    safeStorage: createSafeStorageStub(),
    logger: { warn: () => {}, error: () => {}, debug: () => {}, info: () => {} },
  });
  await mgr.initialize();
  await mgr.applySessionTokens({ access_token: 'A', refresh_token: 'R', desktop_session_version: '5' });
  assert.equal(mgr.getState().authStatus, 'authenticated');

  emit('SIGNED_OUT', null);

  assert.deepStrictEqual(mgr.getState(), { authStatus: 'expired', isLoggedIn: false, user: null });
  assert.deepStrictEqual(mgr.getExpiredCloudIdentity(), { userId: 'U1', sessionVersion: '5' });
  // The persisted session survives an expiry so a restart still knows the account.
  assert.equal(fs.existsSync(path.join(dir, 'supabase-session.enc.json')), true);

  await mgr.signOut();

  assert.deepStrictEqual(mgr.getState(), { authStatus: 'unauthenticated', isLoggedIn: false, user: null });
  assert.equal(mgr.getExpiredCloudIdentity(), null);
});

test('SupabaseSessionManager: a stored session that cannot be restored is exposed as expired', async () => {
  const dir = createTempDir();
  const safeStorage = createSafeStorageStub();
  {
    const { client } = createSupabaseClientStub();
    const mgr = new SupabaseSessionManager({
      createClient: () => client,
      supabaseUrl: 'https://example.supabase.co',
      supabaseAnonKey: 'eyJ.test.test',
      userDataDir: dir,
      safeStorage,
      logger: { warn: () => {}, error: () => {}, debug: () => {}, info: () => {} },
    });
    await mgr.initialize();
    await mgr.applySessionTokens({ access_token: 'A', refresh_token: 'R', desktop_session_version: '9' });
  }

  const { client } = createSupabaseClientStubWithSetSessionFailure();
  const mgr = new SupabaseSessionManager({
    createClient: () => client,
    supabaseUrl: 'https://example.supabase.co',
    supabaseAnonKey: 'eyJ.test.test',
    userDataDir: dir,
    safeStorage,
    extractUserIdFromJwt: (token) => (token === 'A' ? 'U1' : null),
    logger: { warn: () => {}, error: () => {}, debug: () => {}, info: () => {} },
  });
  await mgr.initialize();

  assert.deepStrictEqual(mgr.getState(), { authStatus: 'expired', isLoggedIn: false, user: null });
  assert.deepStrictEqual(mgr.getExpiredCloudIdentity(), { userId: 'U1', sessionVersion: '9' });
  assert.equal(mgr.getAccessToken(), null);
});

test('SupabaseSessionManager: an unauthorized sign-out is an expiry, not an explicit sign-out', async () => {
  const dir = createTempDir();
  const { client } = createSupabaseClientStubWithManualEvents();
  const mgr = new SupabaseSessionManager({
    createClient: () => client,
    supabaseUrl: 'https://example.supabase.co',
    supabaseAnonKey: 'eyJ.test.test',
    userDataDir: dir,
    safeStorage: createSafeStorageStub(),
    logger: { warn: () => {}, error: () => {}, debug: () => {}, info: () => {} },
  });
  await mgr.initialize();
  await mgr.applySessionTokens({ access_token: 'A', refresh_token: 'R', desktop_session_version: '8' });

  await mgr.signOut({ reason: 'unauthorized' });

  assert.deepStrictEqual(mgr.getState(), { authStatus: 'expired', isLoggedIn: false, user: null });
  assert.deepStrictEqual(mgr.getExpiredCloudIdentity(), { userId: 'U1', sessionVersion: '8' });
  assert.equal(fs.existsSync(path.join(dir, 'supabase-session.enc.json')), true);

  await mgr.signOut();

  assert.deepStrictEqual(mgr.getState(), { authStatus: 'unauthenticated', isLoggedIn: false, user: null });
  assert.equal(mgr.getExpiredCloudIdentity(), null);
  assert.equal(fs.existsSync(path.join(dir, 'supabase-session.enc.json')), false);
});

test('SupabaseSessionManager: a second unauthorized sign-out keeps the first expired identity', async () => {
  const dir = createTempDir();
  const { client } = createSupabaseClientStubWithManualEvents();
  const mgr = new SupabaseSessionManager({
    createClient: () => client,
    supabaseUrl: 'https://example.supabase.co',
    supabaseAnonKey: 'eyJ.test.test',
    userDataDir: dir,
    safeStorage: createSafeStorageStub(),
    logger: { warn: () => {}, error: () => {}, debug: () => {}, info: () => {} },
  });
  await mgr.initialize();
  await mgr.applySessionTokens({ access_token: 'A', refresh_token: 'R', desktop_session_version: '8' });

  await mgr.signOut({ reason: 'unauthorized' });
  await mgr.signOut({ reason: 'unauthorized' });

  assert.deepStrictEqual(mgr.getExpiredCloudIdentity(), { userId: 'U1', sessionVersion: '8' });
  assert.deepStrictEqual(mgr.getState(), { authStatus: 'expired', isLoggedIn: false, user: null });
});

test('SupabaseSessionManager: an explicit sign-out racing a 401 is not reclassified as an expiry', async () => {
  const dir = createTempDir();
  const { client } = createSupabaseClientStubWithManualEvents();
  const mgr = new SupabaseSessionManager({
    createClient: () => client,
    supabaseUrl: 'https://example.supabase.co',
    supabaseAnonKey: 'eyJ.test.test',
    userDataDir: dir,
    safeStorage: createSafeStorageStub(),
    logger: { warn: () => {}, error: () => {}, debug: () => {}, info: () => {} },
  });
  await mgr.initialize();
  await mgr.applySessionTokens({ access_token: 'A', refresh_token: 'R', desktop_session_version: '3' });

  await Promise.all([mgr.signOut(), mgr.signOut({ reason: 'unauthorized' })]);

  assert.deepStrictEqual(mgr.getState(), { authStatus: 'unauthenticated', isLoggedIn: false, user: null });
  assert.equal(mgr.getExpiredCloudIdentity(), null);
  assert.equal(fs.existsSync(path.join(dir, 'supabase-session.enc.json')), false);
});

test('SupabaseSessionManager: explicit sign-out removes local auth before a slow remote response', async (t) => {
  const dir = createTempDir();
  t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
  const { client, emit } = createSupabaseClientStubWithManualEvents();
  let finish;
  let applyCount = 0;
  const setSession = client.auth.setSession;
  client.auth.setSession = async (tokens) => { applyCount += 1; return setSession(tokens); };
  client.auth.signOut = () => new Promise((resolve) => { finish = resolve; });
  const mgr = new SupabaseSessionManager({
    createClient: () => client,
    supabaseUrl: 'https://example.supabase.co',
    supabaseAnonKey: 'test-key',
    userDataDir: dir,
    safeStorage: createSafeStorageStub(),
    logger: { warn: () => {}, error: () => {} },
  });
  await mgr.initialize();
  await mgr.applySessionTokens({ access_token: 'A', refresh_token: 'R', desktop_session_version: '3' });

  let nextLogin;
  const signingOut = mgr.signOut();
  await new Promise((resolve) => setImmediate(resolve));
  try {
    assert.equal(mgr.getState().authStatus, 'unauthenticated');
    assert.equal(mgr.getAccessToken(), null);
    assert.equal(mgr.getDesktopSessionVersion(), null);
    assert.equal(fs.existsSync(path.join(dir, 'supabase-session.enc.json')), false);
    emit('TOKEN_REFRESHED', { user: { id: 'U1' }, access_token: 'late-token', refresh_token: 'late-refresh' });
    assert.equal(mgr.getAccessToken(), null);
    assert.equal(mgr.getState().authStatus, 'unauthenticated');
    nextLogin = mgr.applySessionTokens({ access_token: 'new-A', refresh_token: 'new-R', desktop_session_version: '4' });
    await new Promise((resolve) => setImmediate(resolve));
    assert.equal(applyCount, 1);
    assert.equal(fs.existsSync(path.join(dir, 'supabase-session.enc.json')), false);
  } finally {
    finish({ error: null });
    await signingOut;
    if (nextLogin) await nextLogin;
  }
  assert.equal(mgr.getAccessToken(), 'new-A');
});

test('SupabaseSessionManager: failure to delete saved auth cannot report a successful sign-out', async (t) => {
  const dir = createTempDir();
  t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
  const { client, calls } = createSupabaseClientStub();
  const mgr = new SupabaseSessionManager({
    createClient: () => client,
    supabaseUrl: 'https://example.supabase.co',
    supabaseAnonKey: 'test-key',
    userDataDir: dir,
    safeStorage: createSafeStorageStub(),
    logger: { warn: () => {}, error: () => {} },
  });
  await mgr.initialize();
  await mgr.applySessionTokens({ access_token: 'A', refresh_token: 'R', desktop_session_version: '3' });
  t.mock.method(fs, 'unlinkSync', () => { throw Object.assign(new Error('private path'), { code: 'EACCES' }); });

  await assert.rejects(mgr.signOut(), { name: 'CredentialStorageError', code: 'delete_failed' });
  assert.equal(calls.signOut, 0);
  assert.equal(fs.existsSync(path.join(dir, 'supabase-session.enc.json')), true);
});
