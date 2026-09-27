const assert = require('assert');
const { test } = require('node:test');
const fs = require('fs');

function loadRuntimeConfigWithEnv(envOverrides) {
  const modulePath = require.resolve('../electron/runtime_config.js');
  const originalEnv = { ...process.env };
  delete require.cache[modulePath];

  for (const key of Object.keys(process.env)) {
    delete process.env[key];
  }
  Object.assign(process.env, originalEnv, envOverrides);

  try {
    const { loadRuntimeConfig } = require(modulePath);
    return loadRuntimeConfig({ isPackaged: false });
  } finally {
    delete require.cache[modulePath];
    for (const key of Object.keys(process.env)) {
      delete process.env[key];
    }
    Object.assign(process.env, originalEnv);
  }
}

function loadPackagedRuntimeConfigFromJson(jsonText) {
  const modulePath = require.resolve('../electron/runtime_config.js');
  const originalExistsSync = fs.existsSync;
  const originalReadFileSync = fs.readFileSync;
  delete require.cache[modulePath];

  try {
    const { loadRuntimeConfig } = require(modulePath);
    fs.existsSync = () => true;
    fs.readFileSync = () => jsonText;
    return loadRuntimeConfig({ isPackaged: true });
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
  });

  assert.equal(config.backend_url, 'http://127.0.0.1:8005');
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
        })
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
  });

  assert.equal(config.backend_url, 'http://127.0.0.1:8005');
  assert.equal(config.api_host_origin, 'http://127.0.0.1:8005');
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
  });
  assert.equal(config.backend_url, 'http://127.0.0.1:8005');
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
      }),
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
      }),
    /BACKEND_URL must use http:/
  );
});
