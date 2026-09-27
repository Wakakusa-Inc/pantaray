const HELPER_RUNTIME_MANIFEST_FILENAME = 'runtime-manifest.json';
// The staged embedding model, under `.generated` in development and under the
// app's resources in a packaged build. `frontend/scripts/stage-embedding-model.js`
// writes it and `local_backend_runtime_config.js` points the runtime at it.
const LOCAL_EMBEDDING_MODEL_DIRNAME = 'local_embedding_model';
const RUNTIME_MATERIALIZED_KEYS = new Set([
  'LOCAL_DB_PATH',
  'LOCAL_ARTIFACT_ROOT',
  'LOCAL_APP_RUNTIME_MANIFEST_PATH',
  'LOCAL_BACKEND_HELPER_EXECUTABLE',
  'LOCAL_EMBEDDING_MODEL_DIR',
  'LOG_FILE_PATH',
]);
const RUNTIME_PLACEHOLDERS = {
  LOCAL_DB_PATH: '<local_db_path>',
  LOCAL_ARTIFACT_ROOT: '<local_artifact_root>',
  LOCAL_APP_RUNTIME_MANIFEST_PATH: '<local_app_runtime_manifest_path>',
  LOCAL_BACKEND_HELPER_EXECUTABLE: '<local_backend_helper_executable>',
  LOCAL_EMBEDDING_MODEL_DIR: '<local_embedding_model_dir>',
  LOG_FILE_PATH: '<log_file_path>',
};
const BOOLEAN_KEYS = new Set(['USE_MOCKS']);
const INTEGER_KEYS = new Set(['LOCAL_DB_BUSY_TIMEOUT_MS']);
const NODE_ENV_KEY = 'NODE_ENV';
// Python 側 (`agents/src/pantaray_agents/runtime_config.py`) が起動時に要求する値と同一集合。
const VALID_NODE_ENV_VALUES = new Set(['development', 'production', 'test']);
// 配布ビルドでは source env の指定に関わらずこの値を強制する（source env 側の指定は不要）。
const RELEASE_FORCED_VALUES = { NODE_ENV: 'production', LOG_LEVEL: 'ERROR' };
const REQUIRED_LOCAL_BACKEND_KEYS = [
  NODE_ENV_KEY,
  'USE_MOCKS',
  'LOG_LEVEL',
  'ALLOWED_ORIGINS',
  'ALLOWED_HOSTS',
  'LOCAL_DB_BUSY_TIMEOUT_MS',
  'LLM_PROXY_URL',
  'WEB_TOOLS_PROXY_URL',
];

const LOCAL_BACKEND_BUNDLE_KEYS = new Set([
  ...REQUIRED_LOCAL_BACKEND_KEYS,
  ...RUNTIME_MATERIALIZED_KEYS,
]);

function requireKey(env, key) {
  const value = String(env[key] || '').trim();
  if (!value) {
    throw new Error(`Missing local backend env key: ${key}`);
  }
  return value;
}

function parseBoolean(key, rawValue) {
  const normalized = rawValue.toLowerCase();
  if (normalized === 'true') return true;
  if (normalized === 'false') return false;
  throw new Error(`Invalid boolean for ${key}: ${rawValue}`);
}

function parseInteger(key, rawValue) {
  if (!/^-?(0|[1-9][0-9]*)$/.test(rawValue)) {
    throw new Error(`Invalid integer for ${key}: ${rawValue}`);
  }
  return Number.parseInt(rawValue, 10);
}

function requireNodeEnv(rawValue) {
  if (!VALID_NODE_ENV_VALUES.has(rawValue)) {
    throw new Error(
      `Invalid ${NODE_ENV_KEY}: ${rawValue} (must be one of ${[...VALID_NODE_ENV_VALUES].join(', ')})`
    );
  }
  return rawValue;
}

function normalizeValue(key, rawValue) {
  if (key === NODE_ENV_KEY) {
    return requireNodeEnv(rawValue);
  }
  if (BOOLEAN_KEYS.has(key)) {
    return parseBoolean(key, rawValue);
  }
  if (INTEGER_KEYS.has(key)) {
    return parseInteger(key, rawValue);
  }
  return rawValue;
}

function buildLocalBackendRuntimeBundle(env, { releaseBuild = false } = {}) {
  const forcedValues = releaseBuild ? RELEASE_FORCED_VALUES : {};
  const requiredEntries = Object.fromEntries(
    REQUIRED_LOCAL_BACKEND_KEYS.filter((key) => !(key in forcedValues)).map((key) => [
      key,
      normalizeValue(key, requireKey(env, key)),
    ])
  );
  return {
    ...requiredEntries,
    ...forcedValues,
    LOCAL_DB_PATH: RUNTIME_PLACEHOLDERS.LOCAL_DB_PATH,
    LOCAL_ARTIFACT_ROOT: RUNTIME_PLACEHOLDERS.LOCAL_ARTIFACT_ROOT,
    LOCAL_APP_RUNTIME_MANIFEST_PATH: RUNTIME_PLACEHOLDERS.LOCAL_APP_RUNTIME_MANIFEST_PATH,
    LOCAL_BACKEND_HELPER_EXECUTABLE: RUNTIME_PLACEHOLDERS.LOCAL_BACKEND_HELPER_EXECUTABLE,
    LOCAL_EMBEDDING_MODEL_DIR: RUNTIME_PLACEHOLDERS.LOCAL_EMBEDDING_MODEL_DIR,
    LOG_FILE_PATH: RUNTIME_PLACEHOLDERS.LOG_FILE_PATH,
  };
}

/**
 * 配布ビルドの bundle は `os.environ` へそのまま注入されるため、鍵集合を許可リストで固定する。
 * 生成時に通る `buildLocalBackendRuntimeBundle` と同じ集合を、読み込み時にも要求する。
 */
function assertLocalBackendRuntimeBundleKeys(bundle) {
  if (!bundle || typeof bundle !== 'object' || Array.isArray(bundle)) {
    throw new Error('local backend runtime bundle root must be an object.');
  }
  const actual = new Set(Object.keys(bundle));
  const unknown = [...actual].filter((key) => !LOCAL_BACKEND_BUNDLE_KEYS.has(key)).sort();
  const missing = [...LOCAL_BACKEND_BUNDLE_KEYS].filter((key) => !actual.has(key)).sort();
  if (unknown.length === 0 && missing.length === 0) return;
  throw new Error(
    [
      'Invalid local backend runtime bundle key set.',
      ...(unknown.length ? [`unknown=${unknown.join(',')}`] : []),
      ...(missing.length ? [`missing=${missing.join(',')}`] : []),
    ].join(' ')
  );
}

module.exports = {
  HELPER_RUNTIME_MANIFEST_FILENAME,
  LOCAL_BACKEND_BUNDLE_KEYS,
  LOCAL_EMBEDDING_MODEL_DIRNAME,
  RUNTIME_MATERIALIZED_KEYS,
  assertLocalBackendRuntimeBundleKeys,
  buildLocalBackendRuntimeBundle,
};
