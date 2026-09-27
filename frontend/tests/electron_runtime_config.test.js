const assert = require('assert');
const { test } = require('node:test');
const fs = require('fs');

const ACCOUNT_LOGIN_ENABLED = { accountLoginEnabled: true };

function loadRuntimeConfigWithEnv(envOverrides, accountLoginEnabled = false) {
  const modulePath = require.resolve('../electron/runtime_config.js');
  const originalEnv = { ...process.env };
  delete require.cache[modulePath];

  for (const key of Object.keys(process.env)) {
    delete process.env[key];
  }
  Object.assign(process.env, originalEnv, envOverrides);

  try {
    const { loadRuntimeConfig } = require(modulePath);
    return loadRuntimeConfig({ isPackaged: false, accountLoginEnabled });
  } finally {
    delete require.cache[modulePath];
    for (const key of Object.keys(process.env)) {
      delete process.env[key];
    }
    Object.assign(process.env, originalEnv);
  }
}

function loadPackagedRuntimeConfigFromJson(jsonText, accountLoginEnabled) {
  const modulePath = require.resolve('../electron/runtime_config.js');
  const originalExistsSync = fs.existsSync;
  const originalReadFileSync = fs.readFileSync;
  delete require.cache[modulePath];

  try {
    const { loadRuntimeConfig } = require(modulePath);
    fs.existsSync = () => true;
    fs.readFileSync = () => jsonText;
    return loadRuntimeConfig({ isPackaged: true, accountLoginEnabled });
  } finally {
    delete require.cache[modulePath];
    fs.existsSync = originalExistsSync;
    fs.readFileSync = originalReadFileSync;
  }
}

test('loadRuntimeConfig は development でも BACKEND_URL 未設定なら fail closed する', () => {
  assert.throws(
    () =>
      loadRuntimeConfigWithEnv({
        BACKEND_URL: '',
      }),
    /BACKEND_URL must be an absolute URL/
  );
});

test('loadRuntimeConfig は development で BACKEND_URL をそのまま backend_url に使う', () => {
  const config = loadRuntimeConfigWithEnv({
    BACKEND_URL: 'http://127.0.0.1:8005',
    VITE_SUPABASE_URL: 'https://demo.supabase.co',
  });

  assert.equal(config.backend_url, 'http://127.0.0.1:8005');
  // Account login is off: account settings are not read even when present.
  assert.equal('supabase_url' in config, false);
});

const PACKAGED_BACKEND_CONFIG = {
  backend_url: 'http://127.0.0.1:8005',
  api_host_origin: 'http://127.0.0.1:8005',
};

test('loadRuntimeConfig は account login 無効なら account 設定なしの packaged config を受け入れる', () => {
  const config = loadPackagedRuntimeConfigFromJson(JSON.stringify(PACKAGED_BACKEND_CONFIG), false);

  assert.deepEqual(config, PACKAGED_BACKEND_CONFIG);
});

test('loadRuntimeConfig は account login 有効なら account 設定の欠けた packaged config を拒否する', () => {
  assert.throws(
    () => loadPackagedRuntimeConfigFromJson(JSON.stringify(PACKAGED_BACKEND_CONFIG), true),
    /Invalid runtime_config\.json schema/
  );
});

test('loadRuntimeConfig は packaged で backend_url 欠落を許容しない', () => {
  assert.throws(
    () =>
      loadPackagedRuntimeConfigFromJson(
        JSON.stringify({
          web_app_origin: 'https://app.example.test',
          supabase_url: 'https://supabase.example.test',
          supabase_publishable_key: 'sb_publishable_test',
          api_host_origin: 'https://api.example.test',
        }),
        true
      ),
    /Invalid runtime_config\.json schema/
  );
});

test('buildRuntimeConfig は loopback BACKEND_URL を backend_url に出力する', () => {
  const { buildRuntimeConfig } = require('../scripts/generate-electron-runtime-config.js');

  const config = buildRuntimeConfig({
    VITE_WEB_APP_URL: 'https://app.example.test/home',
    VITE_SUPABASE_URL: 'https://demo.supabase.co',
    VITE_SUPABASE_PUBLISHABLE_KEY: 'sb_publishable_test',
    BACKEND_URL: 'http://127.0.0.1:8005',
    VITE_API_HOST: 'http://127.0.0.1:8005',
  }, ACCOUNT_LOGIN_ENABLED);

  assert.equal(config.backend_url, 'http://127.0.0.1:8005');
  assert.equal(config.api_host_origin, 'http://127.0.0.1:8005');
  assert.equal(config.supabase_url, 'https://demo.supabase.co');
});

test('buildRuntimeConfig は CI/release でも loopback BACKEND_URL を許容する', () => {
  const { buildRuntimeConfig } = require('../scripts/generate-electron-runtime-config.js');

  const config = buildRuntimeConfig({
    CI: 'true',
    VITE_WEB_APP_URL: 'https://app.example.test/home',
    VITE_SUPABASE_URL: 'https://demo.supabase.co',
    VITE_SUPABASE_PUBLISHABLE_KEY: 'sb_publishable_test',
    BACKEND_URL: 'http://127.0.0.1:8005',
    VITE_API_HOST: 'http://127.0.0.1:8005',
  }, ACCOUNT_LOGIN_ENABLED);
  assert.equal(config.backend_url, 'http://127.0.0.1:8005');
});

const RELEASE_BACKEND_ENV = {
  PANTARAY_RELEASE_BUILD: '1',
  BACKEND_URL: 'http://127.0.0.1:8005',
  VITE_API_HOST: 'http://127.0.0.1:8005',
};

test('buildRuntimeConfig は account login 無効なら Supabase/Web app の設定なしで release config を作る', () => {
  const { buildRuntimeConfig } = require('../scripts/generate-electron-runtime-config.js');

  assert.deepEqual(buildRuntimeConfig(RELEASE_BACKEND_ENV, { accountLoginEnabled: false }), {
    backend_url: 'http://127.0.0.1:8005',
    api_host_origin: 'http://127.0.0.1:8005',
  });
});

test('buildRuntimeConfig は account login 有効なら Supabase の設定が無いと失敗する', () => {
  const { buildRuntimeConfig } = require('../scripts/generate-electron-runtime-config.js');

  assert.throws(
    () =>
      buildRuntimeConfig(
        { ...RELEASE_BACKEND_ENV, VITE_WEB_APP_URL: 'https://app.example.test' },
        ACCOUNT_LOGIN_ENABLED
      ),
    /Missing env: VITE_SUPABASE_URL/
  );
});


test('buildRuntimeConfig は packaged desktop build で https 以外の VITE_WEB_APP_URL を拒否する', () => {
  const { buildRuntimeConfig } = require('../scripts/generate-electron-runtime-config.js');

  assert.throws(
    () =>
      buildRuntimeConfig({
        PANTARAY_DESKTOP_BUILD_ENV: 'production',
        VITE_WEB_APP_URL: 'http://localhost:3001',
        VITE_SUPABASE_URL: 'https://demo.supabase.co',
        VITE_SUPABASE_PUBLISHABLE_KEY: 'sb_publishable_test',
        BACKEND_URL: 'http://127.0.0.1:8005',
            VITE_API_HOST: 'http://127.0.0.1:8005',
      }, ACCOUNT_LOGIN_ENABLED),
    /VITE_WEB_APP_URL must be https in packaged desktop builds/
  );
});

test('buildRuntimeConfig は packaged desktop build で loopback 以外の BACKEND_URL を拒否する', () => {
  const { buildRuntimeConfig } = require('../scripts/generate-electron-runtime-config.js');

  assert.throws(
    () =>
      buildRuntimeConfig({
        PANTARAY_DESKTOP_BUILD_ENV: 'production',
        VITE_WEB_APP_URL: 'https://app.example.test/home',
        VITE_SUPABASE_URL: 'https://demo.supabase.co',
        VITE_SUPABASE_PUBLISHABLE_KEY: 'sb_publishable_test',
        BACKEND_URL: 'https://api.example.test',
        VITE_API_HOST: 'https://api.example.test',
      }, ACCOUNT_LOGIN_ENABLED),
    /BACKEND_URL must use http:/
  );
});
