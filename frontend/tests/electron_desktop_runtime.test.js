const assert = require('assert');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { test } = require('node:test');

const {
  createDesktopRuntime,
  loadDevelopmentEnvironment,
} = require('../electron/dist/main_runtime/desktopRuntime.js');

const DEVELOPMENT_ENV_KEYS = [
  'BACKEND_URL',
  'VITE_API_HOST',
  'VITE_SUPABASE_PUBLISHABLE_KEY',
  'VITE_SUPABASE_URL',
  'VITE_WEB_APP_URL',
];

function withDevelopmentEnv(callback) {
  const previous = new Map(DEVELOPMENT_ENV_KEYS.map((key) => [key, process.env[key]]));
  Object.assign(process.env, {
    BACKEND_URL: 'http://127.0.0.1:8005',
    VITE_API_HOST: 'https://api.example.com',
    VITE_SUPABASE_PUBLISHABLE_KEY: 'publishable-key',
    VITE_SUPABASE_URL: 'https://supabase.example.com',
    VITE_WEB_APP_URL: 'https://app.example.com',
  });
  try {
    return callback();
  } finally {
    for (const [key, value] of previous) {
      if (value === undefined) delete process.env[key];
      else process.env[key] = value;
    }
  }
}

test('desktop runtime never falls back to a raw URL when the log summarizer returns undefined', () => {
  withDevelopmentEnv(() => {
    const records = [];
    const runtime = createDesktopRuntime({
      app: {
        isPackaged: false,
        getPath: () => '/tmp',
        getLocale: () => 'en',
        quit: () => {},
      },
      dialog: { showErrorBox: () => {} },
      frontendRoot: '/tmp/frontend',
      logger: {
        info: (event, payload) => records.push([event, payload]),
        safeUrlSummary: () => undefined,
      },
    });

    runtime.setBackendUrl('http://127.0.0.1:8010');

    assert.equal(records[0][1].backend_url, undefined);
    assert.equal(records[1][1].backend_url, undefined);
  });
});

test('packaged runtime quits even when the startup error dialog fails', () => {
  let quitCalls = 0;
  const errors = [];

  const runtime = createDesktopRuntime({
    app: {
      isPackaged: true,
      getPath: () => '/tmp',
      getLocale: () => 'en',
      quit: () => {
        quitCalls += 1;
      },
    },
    dialog: {
      showErrorBox: () => {
        throw new Error('dialog unavailable');
      },
    },
    frontendRoot: '/tmp/frontend',
    logger: { error: (event) => errors.push(event) },
  });

  assert.equal(runtime.config, null);
  assert.equal(quitCalls, 1);
  assert.deepEqual(errors, ['RUNTIME_CONFIG_ERR', 'RUNTIME_CONFIG_DIALOG_ERR']);
});

test('development environment loader prefers .env.local', () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'pantaray-desktop-runtime-'));
  fs.writeFileSync(path.join(root, '.env'), 'PANTARAY_RUNTIME_TEST_VALUE=env\n', 'utf8');
  fs.writeFileSync(
    path.join(root, '.env.local'),
    'PANTARAY_RUNTIME_TEST_VALUE=env-local\n',
    'utf8'
  );
  const previous = process.env.PANTARAY_RUNTIME_TEST_VALUE;
  delete process.env.PANTARAY_RUNTIME_TEST_VALUE;
  try {
    loadDevelopmentEnvironment({ frontendRoot: root, isDevelopment: true });
    assert.equal(process.env.PANTARAY_RUNTIME_TEST_VALUE, 'env-local');
  } finally {
    if (previous === undefined) delete process.env.PANTARAY_RUNTIME_TEST_VALUE;
    else process.env.PANTARAY_RUNTIME_TEST_VALUE = previous;
  }
});
