const assert = require('node:assert/strict');
const { createHash } = require('node:crypto');
const fs = require('node:fs');
const http = require('node:http');
const net = require('node:net');
const os = require('node:os');
const path = require('node:path');
const { test } = require('node:test');

const {
  CHATGPT_OAUTH_CLIENT_ID,
  createAuthorizationRequest,
  exchangeAuthorizationCode,
  refreshChatgptTokens,
  startChatgptCallbackListener,
} = require('../electron/dist/auth/chatgptOauth.js');
const { createChatgptTokenStore } = require('../electron/dist/auth/chatgptTokenStore.js');
const { createChatgptLogin } = require('../electron/dist/auth/chatgptLogin.js');

function getFreePort() {
  return new Promise((resolve, reject) => {
    const server = net.createServer();
    server.once('error', reject);
    server.listen(0, '127.0.0.1', () => {
      const { port } = server.address();
      server.close(() => resolve(port));
    });
  });
}

function requestCallback(port, query) {
  return new Promise((resolve, reject) => {
    const req = http.get(`http://127.0.0.1:${port}/auth/callback?${query}`, (res) => {
      res.resume();
      res.on('end', () => resolve(res.statusCode));
    });
    req.once('error', reject);
  });
}

function startListener(port, expectedState) {
  return startChatgptCallbackListener({ port, expectedState, ttlMs: 5_000 });
}

function makeJwt(claims) {
  return `header.${Buffer.from(JSON.stringify(claims)).toString('base64url')}.signature`;
}

function makeAccessToken(accountId, expiresAtMs) {
  return makeJwt({
    exp: Math.floor(expiresAtMs / 1000),
    'https://api.openai.com/auth': { chatgpt_account_id: accountId },
  });
}

function jsonResponse(body, status = 200) {
  return { ok: status >= 200 && status < 300, status, json: async () => body };
}

function recordingFetch(body, status = 200) {
  const calls = [];
  const fetchImpl = async (url, init) => {
    calls.push({ url, init });
    return jsonResponse(body, status);
  };
  return { calls, fetchImpl };
}

function createSafeStorage(available = true) {
  return {
    isEncryptionAvailable: () => available,
    encryptString: (plain) => Buffer.from(`enc:${plain}`, 'utf8'),
    decryptString: (cipher) => cipher.toString('utf8').replace(/^enc:/, ''),
  };
}

/** 受け口のポートは試行ごとに変わりうるので、認可 URL の redirect から読む。 */
function completeCallback(authorizeUrl) {
  const query = new URL(authorizeUrl).searchParams;
  const { port } = new URL(query.get('redirect_uri'));
  return requestCallback(port, `code=auth-code&state=${encodeURIComponent(query.get('state'))}`);
}

function createMemoryStore(initial = null, clearResult = { ok: true }) {
  const state = { tokens: initial, saves: 0, clears: 0 };
  return {
    state,
    load: () => state.tokens,
    save: (tokens) => {
      state.tokens = tokens;
      state.saves += 1;
      return { ok: true };
    },
    clear: () => {
      state.clears += 1;
      if (clearResult.ok) state.tokens = null;
      return clearResult;
    },
  };
}

function storedTokens(expiresAtMs) {
  return {
    accessToken: makeAccessToken('acct_1', expiresAtMs),
    refreshToken: 'refresh-1',
    accountId: 'acct_1',
    expiresAt: new Date(expiresAtMs).toISOString(),
  };
}

function createLogin(t, { store = createMemoryStore(), ports, fetchImpl, openExternal } = {}) {
  const states = [];
  const pending = [];
  const login = createChatgptLogin({
    store,
    ports,
    openExternal: openExternal ?? ((url) => (ports ? completeCallback(url) : Promise.resolve())),
    onStateChanged: (state) => states.push(state),
    fetchImpl: fetchImpl || (() => new Promise((resolve) => pending.push(resolve))),
  });
  // 失敗しても更新タイマーを残さない（残すと実行が終わらない）。
  t.after(() => login.dispose());
  return { login, store, states, pending };
}

/** タイマーを止めている間に、待ち行列の Promise だけを進める。 */
function flushPending() {
  return new Promise((resolve) => setImmediate(resolve));
}

async function waitFor(predicate, message) {
  const deadline = Date.now() + 2_000;
  while (Date.now() < deadline) {
    if (predicate()) return;
    await new Promise((resolve) => setTimeout(resolve, 5));
  }
  throw new Error(message);
}

const SAMPLE_TOKENS = storedTokens(1_800_000_000_000);

test('the authorize url carries the Codex CLI parameters and an S256 challenge', () => {
  const request = createAuthorizationRequest(1455);
  const url = new URL(request.authorizeUrl);
  assert.equal(url.origin + url.pathname, 'https://auth.openai.com/oauth/authorize');
  assert.equal(request.redirectUri, 'http://localhost:1455/auth/callback');
  assert.deepEqual(Object.fromEntries(url.searchParams), {
    response_type: 'code',
    client_id: CHATGPT_OAUTH_CLIENT_ID,
    redirect_uri: 'http://localhost:1455/auth/callback',
    scope: 'openid profile email offline_access',
    code_challenge: createHash('sha256').update(request.codeVerifier).digest('base64url'),
    code_challenge_method: 'S256',
    id_token_add_organizations: 'true',
    codex_cli_simplified_flow: 'true',
    state: request.state,
    originator: 'pantaray',
  });
});

test('the callback listener ignores a mismatched state and stops after the real callback', async () => {
  const port = await getFreePort();
  const started = await startListener(port, 'state-1');
  assert.equal(started.ok, true);

  assert.equal(await requestCallback(port, 'code=attacker&state=other'), 400);
  assert.equal(await requestCallback(port, 'code=real-code&state=state-1'), 200);
  assert.deepEqual(await started.listener.waitForCode(), { ok: true, code: 'real-code' });

  await assert.rejects(requestCallback(port, 'code=late&state=state-1'));
});

test('the callback listener reports authorization failure without echoing provider content', async () => {
  const port = await getFreePort();
  const started = await startListener(port, 'state-2');
  assert.equal(await requestCallback(port, 'state=state-2'), 400);
  assert.deepEqual(await started.listener.waitForCode(), { ok: false, error: 'authorization_failed' });
});

test('a callback denial is told apart from a workspace without Codex', async () => {
  for (const [query, expected] of [
    ['error=access_denied', 'authorization_denied'],
    ['error=access_denied&error_description=missing_codex_entitlement', 'missing_codex_entitlement'],
    ['error=server_error&error_description=upstream', 'authorization_failed'],
  ]) {
    const port = await getFreePort();
    const started = await startListener(port, 'state-3');
    assert.equal(await requestCallback(port, `${query}&state=state-3`), 400);
    assert.deepEqual(await started.listener.waitForCode(), { ok: false, error: expected });
  }
});

test('the authorization code exchange posts the PKCE form and reads the access token claims', async () => {
  const { calls, fetchImpl } = recordingFetch({
    access_token: SAMPLE_TOKENS.accessToken,
    refresh_token: 'refresh-1',
  });
  const result = await exchangeAuthorizationCode({
    code: 'auth-code',
    codeVerifier: 'verifier-1',
    redirectUri: 'http://localhost:1455/auth/callback',
    fetchImpl,
  });

  assert.equal(calls[0].url, 'https://auth.openai.com/oauth/token');
  assert.equal(calls[0].init.headers['Content-Type'], 'application/x-www-form-urlencoded');
  assert.ok(calls[0].init.signal instanceof AbortSignal, 'the token request must be bounded.');
  assert.deepEqual(Object.fromEntries(new URLSearchParams(calls[0].init.body)), {
    grant_type: 'authorization_code',
    code: 'auth-code',
    redirect_uri: 'http://localhost:1455/auth/callback',
    client_id: CHATGPT_OAUTH_CLIENT_ID,
    code_verifier: 'verifier-1',
  });
  assert.deepEqual(result, { ok: true, tokens: SAMPLE_TOKENS });
});

test('a refresh keeps the current refresh token when the response omits one', async () => {
  const { calls, fetchImpl } = recordingFetch({ access_token: SAMPLE_TOKENS.accessToken });
  const result = await refreshChatgptTokens({ refreshToken: 'refresh-1', fetchImpl });

  assert.equal(calls[0].init.headers['Content-Type'], 'application/json');
  assert.deepEqual(JSON.parse(calls[0].init.body), {
    client_id: CHATGPT_OAUTH_CLIENT_ID,
    grant_type: 'refresh_token',
    refresh_token: 'refresh-1',
  });
  assert.deepEqual(result, { ok: true, tokens: SAMPLE_TOKENS });
});

test('a refresh without an access token fails instead of returning partial tokens', async () => {
  const { fetchImpl } = recordingFetch({ error: 'invalid_grant' }, 400);
  const result = await refreshChatgptTokens({ refreshToken: 'refresh-1', fetchImpl });
  assert.deepEqual(result, {
    ok: false,
    error: 'Token endpoint returned status 400.',
    transient: false,
  });
});

test('a refresh rejection tells a temporary outage apart from a spent refresh token', async () => {
  const cases = [
    [{}, 503, true],
    [{}, 401, false],
    [{ error: { code: 'refresh_token_reused' } }, 400, false],
    [{ error: 'server_busy' }, 429, true],
  ];
  for (const [body, status, transient] of cases) {
    const { fetchImpl } = recordingFetch(body, status);
    const result = await refreshChatgptTokens({ refreshToken: 'refresh-1', fetchImpl });
    assert.equal(result.transient, transient, `status ${status} was classified the other way.`);
  }
});

test('the account id is read from the id token when the access token omits it', async () => {
  const expiresAtMs = 1_800_000_000_000;
  const accessToken = makeJwt({ exp: Math.floor(expiresAtMs / 1000) });
  const { fetchImpl } = recordingFetch({
    access_token: accessToken,
    refresh_token: 'refresh-1',
    id_token: makeJwt({ 'https://api.openai.com/auth': { chatgpt_account_id: 'acct_id_token' } }),
  });

  assert.deepEqual(await refreshChatgptTokens({ refreshToken: 'refresh-1', fetchImpl }), {
    ok: true,
    tokens: {
      accessToken,
      refreshToken: 'refresh-1',
      accountId: 'acct_id_token',
      // 期限はアクセストークンのものだけを使う。
      expiresAt: new Date(expiresAtMs).toISOString(),
    },
  });
});

test('an access token with an unrepresentable expiry is rejected', async () => {
  const { fetchImpl } = recordingFetch({ access_token: makeAccessToken('acct_1', 1e21) });
  assert.deepEqual(await refreshChatgptTokens({ refreshToken: 'refresh-1', fetchImpl }), {
    ok: false,
    error: 'The tokens have no usable chatgpt_account_id or exp claim.',
    transient: true,
  });
});

test('the token store round trips through safeStorage and refuses plaintext fallback', () => {
  const userDataDir = fs.mkdtempSync(path.join(os.tmpdir(), 'pantaray-chatgpt-'));
  const storagePath = path.join(userDataDir, 'chatgpt-oauth.enc.json');
  const store = createChatgptTokenStore({ userDataDir, safeStorage: createSafeStorage() });

  assert.equal(store.load(), null);
  assert.deepEqual(store.save(SAMPLE_TOKENS), { ok: true });
  assert.ok(!fs.readFileSync(storagePath, 'utf8').includes(SAMPLE_TOKENS.refreshToken));
  assert.deepEqual(store.load(), SAMPLE_TOKENS);
  assert.deepEqual(store.clear(), { ok: true });
  assert.equal(fs.existsSync(storagePath), false);

  const sealed = createChatgptTokenStore({ userDataDir, safeStorage: createSafeStorage(false) });
  assert.deepEqual(sealed.save(SAMPLE_TOKENS), {
    ok: false,
    error: 'encryption_unavailable',
  });
  assert.deepEqual(fs.readdirSync(userDataDir), []);
});

test('signing in exchanges the loopback callback and publishes the credential', async (t) => {
  const { login, store, states } = createLogin(t, {
    ports: [await getFreePort()],
    fetchImpl: async () =>
      jsonResponse({ access_token: SAMPLE_TOKENS.accessToken, refresh_token: 'refresh-1' }),
  });

  assert.deepEqual(await login.signIn(), {
    ok: true,
    credential: {
      access_token: SAMPLE_TOKENS.accessToken,
      expires_at: SAMPLE_TOKENS.expiresAt,
      account_id: 'acct_1',
    },
  });
  assert.equal(store.state.saves, 1);
  assert.deepEqual(states, [login.getState()]);
});

test('a failed token deletion keeps the connection instead of claiming disconnect', async (t) => {
  const failure = { ok: false, error: 'delete_failed' };
  const { login } = createLogin(t, {
    store: createMemoryStore(storedTokens(Date.now() + 3_600_000), failure),
  });
  assert.deepEqual(login.disconnect(), failure);
  assert.equal(login.getState().status, 'connected');
});

test('a disconnect during the code exchange does not adopt the exchanged tokens', async (t) => {
  const { login, store, pending } = createLogin(t, { ports: [await getFreePort()] });

  const signIn = login.signIn();
  await waitFor(() => pending.length === 1, 'the code exchange never started.');
  assert.deepEqual(login.disconnect(), { ok: true });
  pending[0](jsonResponse({ access_token: SAMPLE_TOKENS.accessToken, refresh_token: 'refresh-1' }));

  assert.deepEqual(await signIn, { ok: false, error: 'cancelled' });
  assert.equal(store.state.saves, 0);
  assert.deepEqual(login.getState(), { status: 'disconnected' });
});

test('a disconnect while the loopback listener starts cancels the sign-in', async (t) => {
  // 中断されなかった場合でも交換が必ず終わるようにして、失敗を待ちぼうけにしない。
  const { login, store } = createLogin(t, {
    ports: [await getFreePort()],
    fetchImpl: async () => jsonResponse({}, 500),
  });

  const signIn = login.signIn();
  login.disconnect();

  assert.deepEqual(await signIn, { ok: false, error: 'cancelled' });
  assert.equal(store.state.saves, 0);
  assert.deepEqual(login.getState(), { status: 'disconnected' });
});

test('a restored credential outside the refresh margin is published without a refresh', async (t) => {
  const { login, states, pending } = createLogin(t, {
    store: createMemoryStore(storedTokens(Date.now() + 3_600_000)),
  });

  assert.equal(login.getState().status, 'connected');
  await new Promise((resolve) => setTimeout(resolve, 20));
  assert.equal(pending.length, 0);
  assert.equal(states.length, 1);
});

test('a credential still inside the margin after a refresh stops instead of looping', async (t) => {
  // 更新後もまだ余裕を切っているトークンを返し、打ち直しが止まることまで見る。
  const refreshedExpiresAtMs = Date.now() + 60_000;
  let calls = 0;
  const { login, store, states } = createLogin(t, {
    store: createMemoryStore(storedTokens(Date.now() + 60_000)),
    fetchImpl: async () => {
      calls += 1;
      return jsonResponse({ access_token: makeAccessToken('acct_1', refreshedExpiresAtMs) });
    },
  });

  assert.equal(login.getState().status, 'disconnected');
  await waitFor(() => states.length === 2, 'the refresh outcome was never published.');
  assert.equal(states[0].status, 'connected');
  assert.equal(states[0].credential.access_token, makeAccessToken('acct_1', refreshedExpiresAtMs));
  // 更新は応答が返さなかった更新トークンを使い回す。
  assert.equal(store.state.tokens.refreshToken, 'refresh-1');
  await new Promise((resolve) => setTimeout(resolve, 30));
  assert.equal(calls, 1);
  assert.deepEqual(states[1], { status: 'reauthentication_required', account_id: 'acct_1' });
});

test('a refresh that lands after a disconnect does not restore the connection', async (t) => {
  const { login, store, pending } = createLogin(t, {
    store: createMemoryStore(storedTokens(Date.now() + 60_000)),
  });

  await waitFor(() => pending.length === 1, 'the scheduled refresh never ran.');
  assert.deepEqual(login.disconnect(), { ok: true });
  assert.equal(store.state.clears, 1);

  pending[0](jsonResponse({ access_token: SAMPLE_TOKENS.accessToken }));
  await new Promise((resolve) => setTimeout(resolve, 20));
  assert.deepEqual(login.getState(), { status: 'disconnected' });
  assert.equal(store.state.saves, 0);
});

test('a refresh that lands after dispose does not reschedule the controller', async (t) => {
  const { login, store, states, pending } = createLogin(t, {
    store: createMemoryStore(storedTokens(Date.now() + 60_000)),
  });

  await waitFor(() => pending.length === 1, 'the scheduled refresh never ran.');
  login.dispose();
  pending[0](jsonResponse({ access_token: SAMPLE_TOKENS.accessToken }));
  await new Promise((resolve) => setTimeout(resolve, 20));
  assert.deepEqual(states, []);
  assert.equal(store.state.saves, 0);
});

test('a refresh the issuer refuses for good asks for reauthentication and keeps the stored tokens', async (t) => {
  const { store, states } = createLogin(t, {
    store: createMemoryStore(storedTokens(Date.now() + 60_000)),
    fetchImpl: async () => jsonResponse({ error: 'invalid_grant' }, 400),
  });

  await waitFor(() => states.length === 1, 'the refresh failure was never published.');
  assert.deepEqual(states[0], { status: 'reauthentication_required', account_id: 'acct_1' });
  assert.equal(store.state.clears, 0);
  assert.equal(store.state.tokens.refreshToken, 'refresh-1');
});

test('a refresh that cannot reach the network is retried instead of ending the connection', async (t) => {
  // スリープ復帰直後は通信が戻っていないだけ。接続を「再認証が必要」に固定しない。
  t.mock.timers.enable({ apis: ['setTimeout'] });
  const refreshedExpiresAtMs = Date.now() + 3_600_000;
  let attempts = 0;
  const { login, states } = createLogin(t, {
    store: createMemoryStore(storedTokens(Date.now() + 60_000)),
    fetchImpl: async () => {
      attempts += 1;
      if (attempts === 1) throw new TypeError('fetch failed');
      return jsonResponse({ access_token: makeAccessToken('acct_1', refreshedExpiresAtMs) });
    },
  });

  // 保存済みトークンは余裕を切っているので、最初の更新はすぐ走る。
  t.mock.timers.tick(0);
  await flushPending();
  assert.equal(attempts, 1);
  assert.deepEqual(states, []);

  t.mock.timers.tick(15_000);
  await flushPending();
  assert.equal(attempts, 2);
  assert.deepEqual(states, [
    { status: 'connected', credential: login.getState().credential },
  ]);
  assert.equal(login.getState().status, 'connected');
});


test('explicit cancellation during exchange preserves an existing connection and rejects late tokens', async (t) => {
  const oldTokens = storedTokens(Date.now() + 3_600_000);
  const { login, store, pending } = createLogin(t, {
    ports: [await getFreePort()],
    store: createMemoryStore(oldTokens),
  });
  const signingIn = login.signIn();
  await waitFor(() => pending.length === 1, 'exchange did not begin');
  login.cancelSignIn();
  pending[0](jsonResponse({ access_token: SAMPLE_TOKENS.accessToken, refresh_token: 'new-refresh' }));
  assert.deepEqual(await signingIn, { ok: false, error: 'cancelled' });
  assert.deepEqual(store.load(), oldTokens);
  assert.equal(login.getState().credential.access_token, oldTokens.accessToken);
});

test('cancelling the loopback wait resolves the attempt and allows a fresh login', async (t) => {
  let opened;
  const { login } = createLogin(t, {
    ports: [await getFreePort()],
    openExternal: async (url) => { opened = url; },
    fetchImpl: async () => jsonResponse({ access_token: SAMPLE_TOKENS.accessToken, refresh_token: 'refresh' }),
  });
  const first = login.signIn();
  await waitFor(() => opened, 'browser did not open');
  login.cancelSignIn();
  assert.deepEqual(await first, { ok: false, error: 'cancelled' });
  assert.equal(login.getState().status, 'disconnected');
  opened = null;
  const second = login.signIn();
  await waitFor(() => opened, 'second browser did not open');
  await completeCallback(opened);
  assert.equal((await second).ok, true);
});

test('browser and exchange failures return fixed codes without provider or native content', async (t) => {
  for (const failure of ['browser_open_failed', 'token_exchange_failed']) {
    const { login } = createLogin(t, {
      ports: [await getFreePort()],
      openExternal: failure === 'browser_open_failed'
        ? async () => { throw new Error('private-auth-code'); }
        : undefined,
      fetchImpl: async () => { throw new Error('private-verifier'); },
    });
    assert.deepEqual(await login.signIn(), { ok: false, error: failure });
    assert.equal(login.getState().status, 'disconnected');
  }
});

test('callback timeout is distinct from cancellation and closes the listener', async () => {
  const port = await getFreePort();
  const started = await startChatgptCallbackListener({ port, expectedState: 'state', ttlMs: 1 });
  assert.equal(started.ok, true);
  assert.deepEqual(await started.listener.waitForCode(), { ok: false, error: 'authorization_timeout' });
  await assert.rejects(requestCallback(port, 'code=late&state=state'));
});


test('an occupied first port moves the whole exchange to the registered fallback port', async (t) => {
  // 同じ client を使う別のアプリがログイン中の状態。redirect が受け口とずれると交換が失敗する。
  const [occupiedPort, fallbackPort] = [await getFreePort(), await getFreePort()];
  const existing = await startListener(occupiedPort, 'other-attempt');
  t.after(() => existing.listener.stop());

  let opened = null;
  const { calls, fetchImpl } = recordingFetch({
    access_token: SAMPLE_TOKENS.accessToken,
    refresh_token: 'refresh-1',
  });
  const { login } = createLogin(t, {
    ports: [occupiedPort, fallbackPort],
    fetchImpl,
    openExternal: async (url) => {
      opened = url;
    },
  });

  const signingIn = login.signIn();
  await waitFor(() => opened, 'the browser was never opened.');
  // 受け口とずれた redirect で認可を頼むと交換が失敗するので、開く前に確かめる。
  const redirectUri = `http://localhost:${fallbackPort}/auth/callback`;
  assert.equal(new URL(opened).searchParams.get('redirect_uri'), redirectUri);

  await completeCallback(opened);
  assert.equal((await signingIn).ok, true);
  assert.equal(new URLSearchParams(calls[0].init.body).get('redirect_uri'), redirectUri);
  // 先に立っていた待ち受けは、こちらのログインに横取りも中断もされない。
  assert.equal(await requestCallback(occupiedPort, 'code=other-code&state=other-attempt'), 200);
  assert.deepEqual(await existing.listener.waitForCode(), { ok: true, code: 'other-code' });
});

test('occupied callback ports are reported without starting token exchange', async (t) => {
  const ports = [await getFreePort(), await getFreePort()];
  const existing = await Promise.all(ports.map((port) => startListener(port, 'other-attempt')));
  t.after(() => existing.forEach((started) => started.listener.stop()));
  const { login, pending } = createLogin(t, { ports });
  assert.deepEqual(await login.signIn(), { ok: false, error: 'listener_unavailable' });
  assert.equal(pending.length, 0);
  assert.equal(login.getState().status, 'disconnected');
});
