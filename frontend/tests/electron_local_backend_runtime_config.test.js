const assert = require('assert');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { test } = require('node:test');
const childProcess = require('child_process');
const crypto = require('crypto');
// The fake recorder must report the pinned release, whatever it is.
const ZANEI_VERSION = require('../electron/zanei_release.json').version;

const {
  DEV_LOCAL_BACKEND_ENV_FILE_ENV,
  LOCAL_BACKEND_RUNTIME_BUNDLE_FILENAME,
  LOCAL_BACKEND_RUNTIME_CONFIG_FILENAME,
  LOCAL_APP_RUNTIME_MANIFEST_FILENAME,
  buildLocalBackendControlSocketPath,
  buildLocalAppRuntimeManifestPath,
  readDevelopmentLocalBackendEnv,
  resolveLoopbackBinding,
  buildMaterializedLocalBackendRuntimeConfig,
  materializeLocalBackendRuntimeConfig,
  materializeDevelopmentLocalBackendRuntimeConfig,
} = require('../electron/local_backend_runtime_config.js');

function createBundleConfig() {
  return {
    NODE_ENV: 'production',
    USE_MOCKS: false,
    LOG_LEVEL: 'INFO',
    ALLOWED_ORIGINS: 'app://.',
    ALLOWED_HOSTS: '127.0.0.1,localhost',
    LOCAL_DB_PATH: '<local_db_path>',
    LOCAL_DB_BUSY_TIMEOUT_MS: 5000,
    LOCAL_ARTIFACT_ROOT: '<local_artifact_root>',
    LOCAL_APP_RUNTIME_MANIFEST_PATH: '<local_app_runtime_manifest_path>',
    LOCAL_BACKEND_HELPER_EXECUTABLE: '<local_backend_helper_executable>',
    LOCAL_EMBEDDING_MODEL_DIR: '<local_embedding_model_dir>',
    LOG_FILE_PATH: '<log_file_path>',
    LLM_PROXY_URL: 'https://llm.example.test',
    WEB_TOOLS_PROXY_URL: 'https://search.example.test',
  };
}

function sha256Text(value) {
  return crypto.createHash('sha256').update(value).digest('hex');
}

test('packaged electron runtime modules は scripts に依存しない', () => {
  const electronDir = path.join(__dirname, '..', 'electron');
  const runtimeModulePaths = fs
    .readdirSync(electronDir)
    .filter((entry) => entry.endsWith('.js'))
    .map((entry) => path.join(electronDir, entry));

  for (const modulePath of runtimeModulePaths) {
    const source = fs.readFileSync(modulePath, 'utf8');
    assert.equal(source.includes("require('../scripts/"), false, modulePath);
    assert.equal(source.includes('require("../scripts/'), false, modulePath);
  }
});

test('resolveLoopbackBinding は BACKEND_URL から loopback bind 情報を導出する', () => {
  assert.deepEqual(resolveLoopbackBinding('http://127.0.0.1:8005'), {
    appPort: 8005,
    bindHost: '127.0.0.1',
    bindPort: 8005,
  });
});

test('buildLocalBackendControlSocketPath は privileged UDS path を組み立てる', () => {
  assert.equal(
    buildLocalBackendControlSocketPath('/tmp/pantaray-user'),
    path.join('/tmp/pantaray-user', 'local-backend', 'control.sock')
  );
});

test('resolveLoopbackBinding は loopback 以外を拒否する', () => {
  assert.throws(() => resolveLoopbackBinding('https://api.example.test'), /must use http:/);
  assert.throws(
    () => resolveLoopbackBinding('http://127.0.0.1:8005/api'),
    /only a loopback origin/
  );
});

test('readDevelopmentLocalBackendEnv は EINTR read を再試行する', () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'pantaray-local-backend-env-eintr-'));
  const envPath = path.join(root, '.env.local.backend.local');
  fs.writeFileSync(envPath, 'BACKEND_URL=http://127.0.0.1:8005\n', 'utf8');

  const originalReadFileSync = fs.readFileSync;
  let envReadCount = 0;
  fs.readFileSync = function readFileSyncWithOneInterruptedRead(filePath, ...args) {
    if (String(filePath) === envPath) {
      envReadCount += 1;
      if (envReadCount === 1) {
        const error = new Error('EINTR: interrupted system call, read');
        error.code = 'EINTR';
        throw error;
      }
    }
    return originalReadFileSync.call(this, filePath, ...args);
  };

  try {
    const result = readDevelopmentLocalBackendEnv(root);
    assert.equal(result.envPath, envPath);
    assert.equal(result.env.BACKEND_URL, 'http://127.0.0.1:8005');
    assert.equal(envReadCount, 2);
  } finally {
    fs.readFileSync = originalReadFileSync;
  }
});

test('readDevelopmentLocalBackendEnv は PANTARAY_LOCAL_BACKEND_ENV_FILE の指定ファイルを読む', () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'pantaray-local-backend-env-override-'));
  fs.writeFileSync(
    path.join(root, '.env.local.backend.local'),
    'BACKEND_URL=http://127.0.0.1:8005\n',
    'utf8'
  );
  const overridePath = path.join(root, 'isolated', '.env.local.backend.e2e');
  fs.mkdirSync(path.dirname(overridePath), { recursive: true });
  fs.writeFileSync(overridePath, 'BACKEND_URL=http://127.0.0.1:9105\n', 'utf8');

  process.env[DEV_LOCAL_BACKEND_ENV_FILE_ENV] = overridePath;
  try {
    const result = readDevelopmentLocalBackendEnv(root);
    assert.equal(result.envPath, overridePath);
    assert.equal(result.env.BACKEND_URL, 'http://127.0.0.1:9105');
  } finally {
    delete process.env[DEV_LOCAL_BACKEND_ENV_FILE_ENV];
  }
});

test('readDevelopmentLocalBackendEnv は PANTARAY_LOCAL_BACKEND_ENV_FILE の相対 path と不存在 path を拒否する', () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'pantaray-local-backend-env-badpath-'));
  try {
    process.env[DEV_LOCAL_BACKEND_ENV_FILE_ENV] = path.join('relative', '.env.local.backend.e2e');
    assert.throws(() => readDevelopmentLocalBackendEnv(root), /must be an absolute path/);
    process.env[DEV_LOCAL_BACKEND_ENV_FILE_ENV] = path.join(root, 'missing.env');
    assert.throws(
      () => readDevelopmentLocalBackendEnv(root),
      /Missing development local backend env file: /
    );
  } finally {
    delete process.env[DEV_LOCAL_BACKEND_ENV_FILE_ENV];
  }
});

test('readDevelopmentLocalBackendEnv は env 未設定時に既存の探索順を使う', () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'pantaray-local-backend-env-default-'));
  fs.writeFileSync(
    path.join(root, '.env.local.backend.local'),
    'BACKEND_URL=http://127.0.0.1:8005\n',
    'utf8'
  );
  fs.writeFileSync(
    path.join(root, '.env.local-runtime.dev'),
    'BACKEND_URL=http://127.0.0.1:9999\n',
    'utf8'
  );
  delete process.env[DEV_LOCAL_BACKEND_ENV_FILE_ENV];

  const result = readDevelopmentLocalBackendEnv(root);
  assert.equal(result.envPath, path.join(root, '.env.local.backend.local'));
  assert.equal(result.env.BACKEND_URL, 'http://127.0.0.1:8005');
});

test('buildMaterializedLocalBackendRuntimeConfig は machine path を userData から固定する', () => {
  const config = buildMaterializedLocalBackendRuntimeConfig(
    createBundleConfig(),
    '/tmp/pantaray-user',
    '/tmp/pantaray-logs',
    '/tmp/resources',
    '/tmp/resources/local_backend_helper/bin/python3',
    '/tmp/pantaray-user/app-runtime-manifest.json'
  );

  assert.equal(config.LOCAL_DB_PATH, path.join('/tmp/pantaray-user', 'local-backend.sqlite3'));
  assert.equal(
    config.LOCAL_ARTIFACT_ROOT,
    path.join('/tmp/pantaray-user', 'local-backend-artifacts')
  );
  assert.equal(
    config.LOCAL_APP_RUNTIME_MANIFEST_PATH,
    '/tmp/pantaray-user/app-runtime-manifest.json'
  );
  assert.equal(
    config.LOCAL_RUNTIME_CONTROL_SOCKET_PATH,
    path.join('/tmp/pantaray-user', 'local-backend', 'control.sock')
  );
  assert.equal(
    config.LOCAL_BACKEND_HELPER_EXECUTABLE,
    path.join('/tmp/resources', 'local_backend_helper', 'bin', 'python3')
  );
  assert.equal(
    config.LOCAL_EMBEDDING_MODEL_DIR,
    path.join('/tmp/resources', 'local_embedding_model')
  );
  assert.equal(config.LOG_FILE_PATH, path.join('/tmp/pantaray-logs', 'pantaray-local-backend.log'));
});

test('buildMaterializedLocalBackendRuntimeConfig は logsDir が空だと失敗する', () => {
  assert.throws(
    () =>
      buildMaterializedLocalBackendRuntimeConfig(
        createBundleConfig(),
        '/tmp/pantaray-user',
        '',
        '/tmp/resources'
      ),
    /logsDir is required/
  );
});

test('materializeLocalBackendRuntimeConfig は bundle を userData 配下へ配置する', (t) => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'pantaray-local-backend-'));
  const resourcesPath = path.join(root, 'resources');
  const userDataDir = path.join(root, 'user-data');
  fs.mkdirSync(resourcesPath, { recursive: true });
  fs.mkdirSync(path.join(resourcesPath, 'local_backend_helper', 'bin'), { recursive: true });
  fs.writeFileSync(
    path.join(resourcesPath, 'local_backend_helper', 'bin', 'python3'),
    'helper-python',
    'utf8'
  );
  fs.writeFileSync(
    path.join(resourcesPath, 'local_backend_helper', 'runtime-manifest.json'),
    JSON.stringify({
      python_version: '3.12.13',
      python_executable_sha256: sha256Text('helper-python'),
    }),
    'utf8'
  );
  fs.writeFileSync(
    path.join(resourcesPath, LOCAL_BACKEND_RUNTIME_BUNDLE_FILENAME),
    JSON.stringify(createBundleConfig()),
    'utf8'
  );

  const zaneiPath = path.join(resourcesPath, 'zanei', 'bin', 'zanei');
  fs.mkdirSync(path.dirname(zaneiPath), { recursive: true });
  const zaneiScript = `#!/bin/sh\necho zanei ${ZANEI_VERSION}\n`;
  fs.writeFileSync(zaneiPath, zaneiScript, { mode: 0o755 });
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  const result = materializeLocalBackendRuntimeConfig({
    resourcesPath,
    userDataDir,
    logsDir: path.join(root, 'logs'),
  });
  const writtenPath = path.join(userDataDir, LOCAL_BACKEND_RUNTIME_CONFIG_FILENAME);
  assert.equal(result.configPath, writtenPath);
  assert.equal(fs.existsSync(writtenPath), true);
  assert.equal(
    result.config.LOCAL_APP_RUNTIME_MANIFEST_PATH,
    path.join(userDataDir, LOCAL_APP_RUNTIME_MANIFEST_FILENAME)
  );
  assert.equal(result.config.LOG_FILE_PATH, path.join(root, 'logs', 'pantaray-local-backend.log'));
  const appRuntimeManifest = JSON.parse(
    fs.readFileSync(path.join(userDataDir, LOCAL_APP_RUNTIME_MANIFEST_FILENAME), 'utf8')
  );
  assert.equal(
    appRuntimeManifest.python_path,
    path.join(resourcesPath, 'local_backend_helper', 'bin', 'python3')
  );
  assert.equal(appRuntimeManifest.python_sha256, sha256Text('helper-python'));
  assert.equal(appRuntimeManifest.zanei.executable_path, fs.realpathSync(zaneiPath));
  assert.equal(appRuntimeManifest.zanei.executable_sha256, sha256Text(zaneiScript));
  assert.equal(appRuntimeManifest.zanei.subject_root, path.join(userDataDir, 'zanei'));
  fs.writeFileSync(zaneiPath, '#!/bin/sh\necho zanei 0.4.0\n');
  assert.throws(
    () =>
      materializeLocalBackendRuntimeConfig({
        resourcesPath,
        userDataDir,
        logsDir: path.join(root, 'logs'),
      }),
    /does not match pinned release/
  );
});

test('materializeLocalBackendRuntimeConfig は bundle の未知の鍵を拒否する', (t) => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'pantaray-local-backend-keys-'));
  const resourcesPath = path.join(root, 'resources');
  fs.mkdirSync(resourcesPath, { recursive: true });
  fs.writeFileSync(
    path.join(resourcesPath, LOCAL_BACKEND_RUNTIME_BUNDLE_FILENAME),
    JSON.stringify({ ...createBundleConfig(), OPENAI_API_KEY: 'sk-injected' }),
    'utf8'
  );
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));

  assert.throws(
    () =>
      materializeLocalBackendRuntimeConfig({
        resourcesPath,
        userDataDir: path.join(root, 'user-data'),
        logsDir: path.join(root, 'logs'),
      }),
    /unknown=OPENAI_API_KEY/
  );
});

test('materializeLocalBackendRuntimeConfig は manifest と helper executable の hash 不一致を拒否する', () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'pantaray-local-backend-signed-'));
  const resourcesPath = path.join(root, 'resources');
  const userDataDir = path.join(root, 'user-data');
  const helperPath = path.join(resourcesPath, 'local_backend_helper', 'bin', 'python3');
  fs.mkdirSync(path.dirname(helperPath), { recursive: true });
  fs.writeFileSync(helperPath, 'helper-python-after-codesign', 'utf8');
  fs.writeFileSync(
    path.join(resourcesPath, 'local_backend_helper', 'runtime-manifest.json'),
    JSON.stringify({
      python_version: '3.12.13',
      python_executable_sha256: 'pre-codesign-hash',
    }),
    'utf8'
  );
  fs.writeFileSync(
    path.join(resourcesPath, LOCAL_BACKEND_RUNTIME_BUNDLE_FILENAME),
    JSON.stringify(createBundleConfig()),
    'utf8'
  );

  assert.throws(
    () =>
      materializeLocalBackendRuntimeConfig({
        resourcesPath,
        userDataDir,
        logsDir: path.join(root, 'logs'),
      }),
    /hash does not match the signed runtime manifest/
  );
});

test('materializeDevelopmentLocalBackendRuntimeConfig は source env から machine-specific path を materialize する', (t) => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'pantaray-dev-env-'));
  const userDataDir = path.join(root, 'user-data');
  const originalExecFileSync = childProcess.execFileSync;
  const zaneiPath = path.resolve(__dirname, '../.generated/zanei/Zanei.app/Contents/MacOS/zanei');
  const originalRead = fs.readFileSync;
  const originalRealpath = fs.realpathSync;
  t.mock.method(fs, 'readFileSync', (file, ...args) =>
    file === zaneiPath ? Buffer.from('dev-zanei') : originalRead(file, ...args)
  );
  t.mock.method(fs, 'realpathSync', (file, ...args) =>
    file === zaneiPath ? zaneiPath : originalRealpath(file, ...args)
  );
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  try {
    childProcess.execFileSync = (file) =>
      file === zaneiPath
        ? `zanei ${ZANEI_VERSION}`
        : JSON.stringify({
            python_path: path.join(root, '.venv', 'bin', 'python3'),
            python_version: '3.12.13',
          });
    fs.mkdirSync(path.join(root, '.venv', 'bin'), { recursive: true });
    fs.writeFileSync(path.join(root, '.venv', 'bin', 'python3'), 'dev-python', 'utf8');
    fs.writeFileSync(
      path.join(root, '.env.local.backend.local'),
      [
        'NODE_ENV=development',
        'USE_MOCKS=false',
        'LOG_LEVEL=INFO',
        'ALLOWED_ORIGINS=http://localhost:3001',
        'ALLOWED_HOSTS=localhost,127.0.0.1',
        'LOCAL_DB_BUSY_TIMEOUT_MS=5000',
        'LLM_PROXY_URL=http://127.0.0.1:8005/v1/llm/proxy',
        'WEB_TOOLS_PROXY_URL=http://127.0.0.1:8005/v1/web-search/proxy',
        '',
      ].join('\n'),
      'utf8'
    );

    assert.deepStrictEqual(readDevelopmentLocalBackendEnv(root).env, {
      NODE_ENV: 'development',
      USE_MOCKS: 'false',
      LOG_LEVEL: 'INFO',
      ALLOWED_ORIGINS: 'http://localhost:3001',
      ALLOWED_HOSTS: 'localhost,127.0.0.1',
      LOCAL_DB_BUSY_TIMEOUT_MS: '5000',
      LLM_PROXY_URL: 'http://127.0.0.1:8005/v1/llm/proxy',
      WEB_TOOLS_PROXY_URL: 'http://127.0.0.1:8005/v1/web-search/proxy',
    });
    const result = materializeDevelopmentLocalBackendRuntimeConfig({
      agentsRoot: root,
      userDataDir,
      logsDir: path.join(root, 'logs'),
    });
    assert.equal(result.sourceEnvPath, path.join(root, '.env.local.backend.local'));
    assert.equal(result.configPath, path.join(userDataDir, LOCAL_BACKEND_RUNTIME_CONFIG_FILENAME));
    assert.equal(result.config.LOCAL_DB_PATH, path.join(userDataDir, 'local-backend.sqlite3'));
    assert.equal(
      result.config.LOCAL_ARTIFACT_ROOT,
      path.join(userDataDir, 'local-backend-artifacts')
    );
    assert.equal(
      result.config.LOCAL_APP_RUNTIME_MANIFEST_PATH,
      path.join(userDataDir, LOCAL_APP_RUNTIME_MANIFEST_FILENAME)
    );
    assert.equal(
      result.config.LOCAL_RUNTIME_CONTROL_SOCKET_PATH,
      path.join(userDataDir, 'local-backend', 'control.sock')
    );
    assert.equal(
      result.config.LOG_FILE_PATH,
      path.join(root, 'logs', 'pantaray-local-backend.log')
    );
    // `stage:embedding-model` writes it there; a checkout that never ran it gets
    // a directory that does not exist, and semantic search stays unavailable.
    assert.equal(
      result.config.LOCAL_EMBEDDING_MODEL_DIR,
      path.resolve(__dirname, '..', '.generated', 'local_embedding_model')
    );
    assert.equal(
      Object.prototype.hasOwnProperty.call(result.config, 'LOCAL_BACKEND_HELPER_EXECUTABLE'),
      false
    );
    const manifest = JSON.parse(
      fs.readFileSync(buildLocalAppRuntimeManifestPath(userDataDir), 'utf8')
    );
    assert.equal(manifest.python_path, path.join(root, '.venv', 'bin', 'python3'));
    assert.equal(manifest.python_version, '3.12.13');
  } finally {
    childProcess.execFileSync = originalExecFileSync;
  }
});
