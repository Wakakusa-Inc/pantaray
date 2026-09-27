const assert = require('assert');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { test } = require('node:test');

const {
  DEVELOPMENT_LOCAL_BACKEND_ENV_PATH,
  PRODUCTION_LOCAL_BACKEND_ENV_PATH,
  readLocalBackendEnv,
  resolveLocalBackendEnvPath,
  requireLocalBackendEnvPath,
} = require('../scripts/prepare-local-backend-runtime-bundle.js');
const {
  RUNTIME_MATERIALIZED_KEYS,
  assertLocalBackendRuntimeBundleKeys,
  buildLocalBackendRuntimeBundle,
  localBackendBundleKeys,
} = require('../electron/local_backend_runtime_bundle.js');

const DISABLED = { accountLoginEnabled: false };
const ENABLED = { accountLoginEnabled: true };

function collectPlaceholderPaths(value, keyPath = []) {
  if (typeof value === 'string' && /^<.+>$/.test(value)) {
    return [keyPath.join('.')];
  }
  if (Array.isArray(value)) {
    return value.flatMap((item, index) =>
      collectPlaceholderPaths(item, [...keyPath, String(index)])
    );
  }
  if (!value || typeof value !== 'object') {
    return [];
  }
  return Object.entries(value).flatMap(([key, nestedValue]) =>
    collectPlaceholderPaths(nestedValue, [...keyPath, key])
  );
}

function createPackagedLocalBackendEnv() {
  return {
    NODE_ENV: 'production',
    USE_MOCKS: 'false',
    LOG_LEVEL: 'INFO',
    ALLOWED_ORIGINS: 'app://.',
    ALLOWED_HOSTS: '127.0.0.1,localhost',
    LOCAL_DB_BUSY_TIMEOUT_MS: '5000',
  };
}

const CLOUD_PROXY_ENV = {
  LLM_PROXY_URL: 'https://llm.example.test',
  WEB_TOOLS_PROXY_URL: 'https://search.example.test',
};

test('buildLocalBackendRuntimeBundle は local backend env から値を解決する', () => {
  const bundle = buildLocalBackendRuntimeBundle(createPackagedLocalBackendEnv(), DISABLED);

  assert.equal(bundle.LOCAL_DB_BUSY_TIMEOUT_MS, 5000);
  assert.equal(bundle.USE_MOCKS, false);
  assert.equal(bundle.LOCAL_APP_RUNTIME_MANIFEST_PATH, '<local_app_runtime_manifest_path>');
});

test('buildLocalBackendRuntimeBundle は releaseBuild で NODE_ENV/LOG_LEVEL を強制する', () => {
  const bundle = buildLocalBackendRuntimeBundle(
    { ...createPackagedLocalBackendEnv(), NODE_ENV: 'development', LOG_LEVEL: 'INFO' },
    { ...DISABLED, releaseBuild: true }
  );

  assert.equal(bundle.NODE_ENV, 'production');
  assert.equal(bundle.LOG_LEVEL, 'ERROR');
});

test('buildLocalBackendRuntimeBundle は releaseBuild 無しでは env の値を維持する', () => {
  const bundle = buildLocalBackendRuntimeBundle(
    { ...createPackagedLocalBackendEnv(), NODE_ENV: 'development', LOG_LEVEL: 'INFO' },
    DISABLED
  );

  assert.equal(bundle.NODE_ENV, 'development');
  assert.equal(bundle.LOG_LEVEL, 'INFO');
});

test('buildLocalBackendRuntimeBundle は releaseBuild 時 強制対象が未指定の env でも成功する', () => {
  const env = { ...createPackagedLocalBackendEnv() };
  delete env.LOG_LEVEL;
  delete env.NODE_ENV;

  const bundle = buildLocalBackendRuntimeBundle(env, { ...DISABLED, releaseBuild: true });

  assert.equal(bundle.NODE_ENV, 'production');
  assert.equal(bundle.LOG_LEVEL, 'ERROR');
});

test('buildLocalBackendRuntimeBundle は不正な NODE_ENV を拒否する', () => {
  for (const nodeEnv of ['dproduction', 'prodction', 'prod', 'Production', 'PRODUCTION']) {
    assert.throws(
      () =>
        buildLocalBackendRuntimeBundle(
          { ...createPackagedLocalBackendEnv(), NODE_ENV: nodeEnv },
          DISABLED
        ),
      new RegExp(`Invalid NODE_ENV: ${nodeEnv}`),
      `NODE_ENV=${nodeEnv} must fail bundle generation`
    );
  }
});

test('buildLocalBackendRuntimeBundle は正しい NODE_ENV をそのまま採用する', () => {
  for (const nodeEnv of ['development', 'production', 'test']) {
    const bundle = buildLocalBackendRuntimeBundle(
      { ...createPackagedLocalBackendEnv(), NODE_ENV: nodeEnv },
      DISABLED
    );

    assert.equal(bundle.NODE_ENV, nodeEnv);
  }
});

test('buildLocalBackendRuntimeBundle は required env が欠けると失敗する', () => {
  assert.throws(() => buildLocalBackendRuntimeBundle({}, DISABLED), /Missing local backend env key/);
});

test('buildLocalBackendRuntimeBundle は account login 有効時だけ Cloud proxy URL を要求し同梱する', () => {
  const disabled = buildLocalBackendRuntimeBundle(
    { ...createPackagedLocalBackendEnv(), ...CLOUD_PROXY_ENV },
    DISABLED
  );
  assert.equal('LLM_PROXY_URL' in disabled, false);
  assert.equal('WEB_TOOLS_PROXY_URL' in disabled, false);

  assert.throws(
    () => buildLocalBackendRuntimeBundle(createPackagedLocalBackendEnv(), ENABLED),
    /Missing local backend env key: LLM_PROXY_URL/
  );
  const enabled = buildLocalBackendRuntimeBundle(
    { ...createPackagedLocalBackendEnv(), ...CLOUD_PROXY_ENV },
    ENABLED
  );
  assert.equal(enabled.LLM_PROXY_URL, 'https://llm.example.test');
  assert.equal(enabled.WEB_TOOLS_PROXY_URL, 'https://search.example.test');
});

test('buildLocalBackendRuntimeBundle は runtime 専用 placeholder だけを残す', () => {
  const bundle = buildLocalBackendRuntimeBundle(
    { ...createPackagedLocalBackendEnv(), ...CLOUD_PROXY_ENV },
    ENABLED
  );

  const placeholderPaths = collectPlaceholderPaths(bundle);
  assert.deepEqual(
    placeholderPaths.sort(),
    [...RUNTIME_MATERIALIZED_KEYS].sort().map((key) => key)
  );
});

test('resolveLocalBackendEnvPath は build mode ごとの env file を選ぶ', () => {
  const originalVersion = process.env.PANTARAY_DESKTOP_VERSION;
  const originalBuildEnv = process.env.PANTARAY_DESKTOP_BUILD_ENV;
  delete process.env.PANTARAY_DESKTOP_VERSION;
  delete process.env.PANTARAY_DESKTOP_BUILD_ENV;
  assert.equal(resolveLocalBackendEnvPath(), DEVELOPMENT_LOCAL_BACKEND_ENV_PATH);

  process.env.PANTARAY_DESKTOP_BUILD_ENV = 'production';
  assert.equal(resolveLocalBackendEnvPath(), PRODUCTION_LOCAL_BACKEND_ENV_PATH);

  process.env.PANTARAY_DESKTOP_BUILD_ENV = 'local';
  process.env.PANTARAY_DESKTOP_VERSION = '1.2.3';
  assert.throws(
    () => resolveLocalBackendEnvPath(),
    /PANTARAY_DESKTOP_BUILD_ENV cannot be "local" in release builds/
  );

  delete process.env.PANTARAY_DESKTOP_BUILD_ENV;
  assert.equal(resolveLocalBackendEnvPath(), PRODUCTION_LOCAL_BACKEND_ENV_PATH);

  if (originalVersion === undefined) {
    delete process.env.PANTARAY_DESKTOP_VERSION;
  } else {
    process.env.PANTARAY_DESKTOP_VERSION = originalVersion;
  }
  if (originalBuildEnv === undefined) {
    delete process.env.PANTARAY_DESKTOP_BUILD_ENV;
  } else {
    process.env.PANTARAY_DESKTOP_BUILD_ENV = originalBuildEnv;
  }
});

test('requireLocalBackendEnvPath は存在しない env file を拒否する', () => {
  const originalVersion = process.env.PANTARAY_DESKTOP_VERSION;
  const originalBuildEnv = process.env.PANTARAY_DESKTOP_BUILD_ENV;
  process.env.PANTARAY_DESKTOP_BUILD_ENV = 'production';

  const originalExistsSync = fs.existsSync;
  fs.existsSync = () => false;

  try {
    assert.throws(() => requireLocalBackendEnvPath(), /Missing local backend env file/);
  } finally {
    fs.existsSync = originalExistsSync;
    if (originalVersion === undefined) {
      delete process.env.PANTARAY_DESKTOP_VERSION;
    } else {
      process.env.PANTARAY_DESKTOP_VERSION = originalVersion;
    }
    if (originalBuildEnv === undefined) {
      delete process.env.PANTARAY_DESKTOP_BUILD_ENV;
    } else {
      process.env.PANTARAY_DESKTOP_BUILD_ENV = originalBuildEnv;
    }
  }
});

test('readLocalBackendEnv は env file を key-value mapping として読む', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'local-backend-env-'));
  const envPath = path.join(dir, '.env.local.backend.production');
  fs.writeFileSync(envPath, 'NODE_ENV=production\nUSE_MOCKS=false\n', 'utf8');

  assert.deepEqual(readLocalBackendEnv(envPath), {
    NODE_ENV: 'production',
    USE_MOCKS: 'false',
  });
});

test('buildLocalBackendRuntimeBundle の鍵集合は allowlist と一致する', () => {
  const env = { ...createPackagedLocalBackendEnv(), ...CLOUD_PROXY_ENV };
  for (const options of [DISABLED, ENABLED]) {
    const expected = [...localBackendBundleKeys(options.accountLoginEnabled)].sort();
    const bundle = buildLocalBackendRuntimeBundle(env, options);
    assert.deepEqual(Object.keys(bundle).sort(), expected);
    assert.doesNotThrow(() => assertLocalBackendRuntimeBundleKeys(bundle, options));

    // 配布ビルドが実際に通る経路（NODE_ENV / LOG_LEVEL を差し替える）でも鍵集合は変わらない。
    const released = buildLocalBackendRuntimeBundle(env, { ...options, releaseBuild: true });
    assert.deepEqual(Object.keys(released).sort(), expected);
  }
});

test('assertLocalBackendRuntimeBundleKeys は未知/欠落した鍵を拒否する', () => {
  const bundle = buildLocalBackendRuntimeBundle(createPackagedLocalBackendEnv(), DISABLED);

  assert.throws(
    () =>
      assertLocalBackendRuntimeBundleKeys({ ...bundle, OPENAI_API_KEY: 'sk-injected' }, DISABLED),
    /unknown=OPENAI_API_KEY/
  );
  const { LOG_FILE_PATH: _removed, ...withoutLogFilePath } = bundle;
  assert.throws(
    () => assertLocalBackendRuntimeBundleKeys(withoutLogFilePath, DISABLED),
    /missing=LOG_FILE_PATH/
  );
  assert.throws(
    () => assertLocalBackendRuntimeBundleKeys(bundle, ENABLED),
    /missing=LLM_PROXY_URL,WEB_TOOLS_PROXY_URL/
  );
  assert.throws(() => assertLocalBackendRuntimeBundleKeys([], DISABLED), /root must be an object/);
});
