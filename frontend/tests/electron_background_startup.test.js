const assert = require('assert');
const { test } = require('node:test');

const {
  startDesktopBackgroundRuntime,
} = require('../electron/dist/main_runtime/backgroundStartup.js');

function createParams(overrides = {}) {
  const calls = [];
  const errors = [];
  return {
    calls,
    errors,
    params: {
      installLocalBackendConfig: () => calls.push('config'),
      ensureLocalBackendStarted: async () => calls.push('helper'),
      initializeAuth: async () => calls.push('auth'),
      applyPendingAuthCallback: () => calls.push('callback'),
      ensureOrchestrationConnected: () => calls.push('orchestration'),
      reportRuntimeConfigFailure: () => calls.push('fatal'),
      logger: { error: (event) => errors.push(event) },
      ...overrides,
    },
  };
}

test('background startup preserves the required initialization order', async () => {
  const { calls, params } = createParams();

  await startDesktopBackgroundRuntime(params);

  assert.deepEqual(calls, [
    'config',
    'helper',
    'auth',
    'callback',
    'orchestration',
  ]);
});

test('background startup stops after a runtime config failure', async () => {
  const failure = new Error('invalid config');
  const { calls, errors, params } = createParams({
    installLocalBackendConfig: () => {
      calls.push('config');
      throw failure;
    },
    reportRuntimeConfigFailure: (error) => {
      assert.equal(error, failure);
      calls.push('fatal');
    },
  });

  await startDesktopBackgroundRuntime(params);

  assert.deepEqual(calls, ['config', 'fatal']);
  assert.deepEqual(errors, ['LOCAL_BACKEND_RUNTIME_CONFIG_ERR']);
});

test('background startup logs recoverable service failures and continues', async () => {
  const { calls, errors, params } = createParams({
    ensureLocalBackendStarted: async () => {
      calls.push('helper');
      throw new Error('helper failed');
    },
    initializeAuth: async () => {
      calls.push('auth');
      throw new Error('auth failed');
    },
  });

  await startDesktopBackgroundRuntime(params);

  assert.deepEqual(calls, [
    'config',
    'helper',
    'auth',
    'callback',
    'orchestration',
  ]);
  assert.deepEqual(errors, ['LOCAL_BACKEND_HELPER_START_ERR', 'SUPABASE_WIRING_INIT_ERR']);
});

test('background startup waits for the helper before connecting orchestration', async () => {
  let releaseHelper;
  const helperReady = new Promise((resolve) => { releaseHelper = resolve; });
  const { calls, params } = createParams({ ensureLocalBackendStarted: () => helperReady });
  const startup = startDesktopBackgroundRuntime(params);
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(calls.includes('callback'), true);
  assert.equal(calls.includes('orchestration'), false);
  releaseHelper();
  await startup;
  assert.equal(calls.at(-1), 'orchestration');
});
