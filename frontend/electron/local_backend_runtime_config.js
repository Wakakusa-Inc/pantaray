const fs = require('fs');
const nodeCrypto = require('crypto');
const path = require('path');
const childProcess = require('child_process');
const dotenv = require('dotenv');
const {
  assertLocalBackendRuntimeBundleKeys,
  buildLocalBackendRuntimeBundle,
  HELPER_RUNTIME_MANIFEST_FILENAME,
  LOCAL_EMBEDDING_MODEL_DIRNAME,
} = require('./local_backend_runtime_bundle.js');
const { resolveLoopbackBinding } = require('./loopback_backend_url.js');

const LOCAL_BACKEND_RUNTIME_BUNDLE_FILENAME = 'local_backend_runtime.bundle.json';
const LOCAL_BACKEND_RUNTIME_CONFIG_FILENAME = 'env.local.backend.json';
const LOCAL_BACKEND_CONTROL_SOCKET_DIRNAME = 'local-backend';
const LOCAL_BACKEND_CONTROL_SOCKET_FILENAME = 'control.sock';
const LOCAL_BACKEND_HELPER_RUNTIME_DIRNAME = 'local_backend_helper';
const LOCAL_BACKEND_HELPER_EXECUTABLE_RELATIVE_PATH = path.join(
  LOCAL_BACKEND_HELPER_RUNTIME_DIRNAME,
  'bin',
  'python3'
);
const LOCAL_APP_RUNTIME_MANIFEST_FILENAME = 'app-runtime-manifest.json';
// Python local-backend log filename, written into the same logs dir as the
// Electron main log (app.getPath('logs')). Distinct name so the two never collide.
const PYTHON_LOG_FILENAME = 'pantaray-local-backend.log';
const DEVELOPMENT_ENV_FILENAMES = [
  '.env.local.backend.local',
  '.env.local-runtime.dev',
  '.env.local-runtime',
];
// Dev-only override: readDevelopmentLocalBackendEnv is reachable only through the
// development materialization path (desktopRuntime.ts gates on app.isPackaged), so
// packaged apps never consult this variable.
const DEV_LOCAL_BACKEND_ENV_FILE_ENV = 'PANTARAY_LOCAL_BACKEND_ENV_FILE';
const INTERRUPTED_READ_RETRY_LIMIT = 8;
const PLACEHOLDER_PATTERN = /^<.+>$/;

function isPlainObject(value) {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value);
}

function isInterruptedReadError(error) {
  return (
    error &&
    typeof error === 'object' &&
    (error.code === 'EINTR' ||
      String(error.message || '')
        .toLowerCase()
        .includes('interrupted system call, read'))
  );
}

function readFileSyncWithInterruptedReadRetry(filePath, options) {
  let lastInterruptedError = null;
  for (let attempt = 0; attempt <= INTERRUPTED_READ_RETRY_LIMIT; attempt += 1) {
    try {
      return fs.readFileSync(filePath, options);
    } catch (error) {
      if (!isInterruptedReadError(error)) {
        throw error;
      }
      lastInterruptedError = error;
    }
  }
  throw lastInterruptedError;
}

function sha256File(filePath) {
  const digest = nodeCrypto.createHash('sha256');
  digest.update(readFileSyncWithInterruptedReadRetry(filePath));
  return digest.digest('hex');
}

function assertNoUnresolvedPlaceholders(value, keyPath, overridableKeys) {
  if (typeof value === 'string' && PLACEHOLDER_PATTERN.test(value)) {
    if (overridableKeys.has(keyPath[keyPath.length - 1] || '')) {
      return;
    }
    throw new Error(`Unresolved placeholder in local backend runtime bundle: ${keyPath.join('.')}`);
  }

  if (Array.isArray(value)) {
    value.forEach((item, index) =>
      assertNoUnresolvedPlaceholders(item, [...keyPath, String(index)], overridableKeys)
    );
    return;
  }

  if (!isPlainObject(value)) {
    return;
  }

  for (const [key, nestedValue] of Object.entries(value)) {
    assertNoUnresolvedPlaceholders(nestedValue, [...keyPath, key], overridableKeys);
  }
}

/**
 * Where the build staged the embedding model, packaged or in development.
 *
 * Nothing checks that the directory exists: a runtime that finds no usable model
 * keeps running and reports semantic memory search as unavailable, which is what
 * a development checkout without `stage:embedding-model` should get.
 */
function buildLocalEmbeddingModelDir(resourcesPath) {
  return typeof resourcesPath === 'string' && resourcesPath.trim()
    ? path.join(resourcesPath.trim(), LOCAL_EMBEDDING_MODEL_DIRNAME)
    : path.resolve(__dirname, '..', '.generated', LOCAL_EMBEDDING_MODEL_DIRNAME);
}

function buildLocalBackendControlSocketPath(runtimeRootDir) {
  return path.join(
    runtimeRootDir,
    LOCAL_BACKEND_CONTROL_SOCKET_DIRNAME,
    LOCAL_BACKEND_CONTROL_SOCKET_FILENAME
  );
}

function buildLocalAppRuntimeManifestPath(userDataDir) {
  return path.join(userDataDir, LOCAL_APP_RUNTIME_MANIFEST_FILENAME);
}

function readDevelopmentLocalBackendEnv(agentsRoot) {
  const overridePath = String(process.env[DEV_LOCAL_BACKEND_ENV_FILE_ENV] ?? '').trim();
  if (overridePath) {
    if (!path.isAbsolute(overridePath)) {
      throw new Error(`${DEV_LOCAL_BACKEND_ENV_FILE_ENV} must be an absolute path.`);
    }
    if (!fs.existsSync(overridePath)) {
      throw new Error(`Missing development local backend env file: ${overridePath}`);
    }
    return {
      envPath: overridePath,
      env: dotenv.parse(readFileSyncWithInterruptedReadRetry(overridePath, 'utf8')),
    };
  }
  for (const filename of DEVELOPMENT_ENV_FILENAMES) {
    const envPath = path.join(agentsRoot, filename);
    if (!fs.existsSync(envPath)) {
      continue;
    }
    return {
      envPath,
      env: dotenv.parse(readFileSyncWithInterruptedReadRetry(envPath, 'utf8')),
    };
  }
  throw new Error(`Missing development local backend env file under: ${agentsRoot}`);
}

function writeJsonAtomically(targetPath, payload) {
  const tmpPath = `${targetPath}.tmp`;
  fs.mkdirSync(path.dirname(targetPath), { recursive: true });
  fs.writeFileSync(tmpPath, `${JSON.stringify(payload, null, 2)}\n`, {
    encoding: 'utf8',
    mode: 0o600,
  });
  fs.renameSync(tmpPath, targetPath);
}

function readZaneiRuntimeInfo({ userDataDir, resourcesPath }) {
  const release = require('./zanei_release.json');
  const executablePath = resourcesPath
    ? path.join(resourcesPath, 'zanei', 'bin', 'zanei')
    : path.resolve(
        __dirname,
        '..',
        '.generated',
        'zanei',
        'Zanei.app',
        'Contents',
        'MacOS',
        'zanei'
      );
  const version = childProcess
    .execFileSync(executablePath, ['--version'], {
      encoding: 'utf8',
      timeout: 10000,
    })
    .trim();
  if (version !== `zanei ${release.version}`) {
    throw new Error(`Zanei runtime version does not match pinned release ${release.version}.`);
  }
  return {
    executable_path: fs.realpathSync(executablePath),
    executable_sha256: sha256File(executablePath),
    protocol_version: 1,
    subject_root: path.resolve(userDataDir, 'zanei'),
    keychain_service_prefix: 'com.pantaray.context.store',
    keychain_label_prefix: 'Pantaray Context Store',
  };
}

function writeLocalAppRuntimeManifest({
  manifestPath,
  pythonPath,
  pythonVersion,
  pythonSha256,
  zanei,
}) {
  writeJsonAtomically(manifestPath, {
    python_path: path.resolve(String(pythonPath)),
    python_version: String(pythonVersion),
    python_sha256: String(pythonSha256),
    zanei,
  });
}

function resolveDevelopmentAppRuntimeInfo(agentsRoot) {
  const raw = childProcess.execFileSync(
    'uv',
    [
      'run',
      'python',
      '-c',
      [
        'import json',
        'import platform',
        'import sys',
        'from pathlib import Path',
        'print(json.dumps({"python_path": str(Path(sys.executable).resolve()), "python_version": platform.python_version()}))',
      ].join('; '),
    ],
    {
      cwd: agentsRoot,
      env: {
        ...process.env,
        PYTHONNOUSERSITE: '1',
      },
      encoding: 'utf8',
    }
  );
  const parsed = JSON.parse(String(raw).trim());
  if (!isPlainObject(parsed)) {
    throw new Error('Development app runtime probe must return a JSON object.');
  }
  const pythonPath = String(parsed.python_path || '').trim();
  const pythonVersion = String(parsed.python_version || '').trim();
  if (!pythonPath || !pythonVersion) {
    throw new Error('Development app runtime probe returned incomplete python metadata.');
  }
  return {
    pythonPath,
    pythonVersion,
    pythonSha256: sha256File(pythonPath),
  };
}

function readPackagedHelperRuntimeMetadata(resourcesPath) {
  const metadataPath = path.join(
    resourcesPath,
    LOCAL_BACKEND_HELPER_RUNTIME_DIRNAME,
    HELPER_RUNTIME_MANIFEST_FILENAME
  );
  if (!fs.existsSync(metadataPath)) {
    throw new Error(`Missing helper runtime metadata manifest: ${metadataPath}`);
  }
  const parsed = JSON.parse(readFileSyncWithInterruptedReadRetry(metadataPath, 'utf8'));
  if (!isPlainObject(parsed)) {
    throw new Error('Helper runtime metadata manifest must be an object.');
  }
  const pythonVersion = String(parsed.python_version || '').trim();
  const pythonSha256 = String(parsed.python_executable_sha256 || '').trim();
  if (!pythonVersion || !pythonSha256) {
    throw new Error('Helper runtime metadata manifest is missing python executable metadata.');
  }
  return {
    pythonVersion,
    pythonSha256,
  };
}

function materializeDevelopmentAppRuntimeManifest({ agentsRoot, userDataDir }) {
  const manifestPath = buildLocalAppRuntimeManifestPath(userDataDir);
  const runtimeInfo = resolveDevelopmentAppRuntimeInfo(agentsRoot);
  writeLocalAppRuntimeManifest({
    manifestPath,
    ...runtimeInfo,
    zanei: readZaneiRuntimeInfo({ userDataDir }),
  });
  return manifestPath;
}

function materializePackagedAppRuntimeManifest({
  resourcesPath,
  userDataDir,
  helperExecutablePath,
}) {
  const manifestPath = buildLocalAppRuntimeManifestPath(userDataDir);
  const runtimeInfo = readPackagedHelperRuntimeMetadata(resourcesPath);
  const actualPythonSha256 = sha256File(helperExecutablePath);
  if (actualPythonSha256 !== runtimeInfo.pythonSha256) {
    throw new Error(
      [
        'Packaged helper python executable hash does not match the signed runtime manifest.',
        `path=${helperExecutablePath}`,
        `expected=${runtimeInfo.pythonSha256}`,
        `actual=${actualPythonSha256}`,
      ].join(' ')
    );
  }
  writeLocalAppRuntimeManifest({
    manifestPath,
    pythonPath: helperExecutablePath,
    pythonVersion: runtimeInfo.pythonVersion,
    pythonSha256: runtimeInfo.pythonSha256,
    zanei: readZaneiRuntimeInfo({ userDataDir, resourcesPath }),
  });
  return manifestPath;
}

function buildMaterializedLocalBackendRuntimeConfig(
  bundleConfig,
  userDataDir,
  logsDir,
  resourcesPath,
  helperExecutablePath = null,
  appRuntimeManifestPath = null
) {
  if (!isPlainObject(bundleConfig)) {
    throw new Error('local backend runtime bundle root must be an object.');
  }
  if (typeof logsDir !== 'string' || !logsDir.trim()) {
    throw new Error('logsDir is required to materialize LOG_FILE_PATH for the local backend.');
  }

  const materializedConfig = {
    ...bundleConfig,
    LOCAL_DB_PATH: path.join(userDataDir, 'local-backend.sqlite3'),
    LOCAL_ARTIFACT_ROOT: path.join(userDataDir, 'local-backend-artifacts'),
    LOCAL_RUNTIME_CONTROL_SOCKET_PATH: buildLocalBackendControlSocketPath(userDataDir),
    LOCAL_EMBEDDING_MODEL_DIR: buildLocalEmbeddingModelDir(resourcesPath),
    LOG_FILE_PATH: path.join(logsDir, PYTHON_LOG_FILENAME),
  };
  if (typeof helperExecutablePath === 'string' && helperExecutablePath.trim()) {
    materializedConfig.LOCAL_BACKEND_HELPER_EXECUTABLE = helperExecutablePath.trim();
  } else if (typeof resourcesPath === 'string' && resourcesPath.trim()) {
    materializedConfig.LOCAL_BACKEND_HELPER_EXECUTABLE = path.join(
      resourcesPath,
      LOCAL_BACKEND_HELPER_EXECUTABLE_RELATIVE_PATH
    );
  } else {
    delete materializedConfig.LOCAL_BACKEND_HELPER_EXECUTABLE;
  }
  if (typeof appRuntimeManifestPath === 'string' && appRuntimeManifestPath.trim()) {
    materializedConfig.LOCAL_APP_RUNTIME_MANIFEST_PATH = appRuntimeManifestPath.trim();
  } else {
    delete materializedConfig.LOCAL_APP_RUNTIME_MANIFEST_PATH;
  }

  const overridableKeys = new Set([
    'LOCAL_DB_PATH',
    'LOCAL_ARTIFACT_ROOT',
    'LOCAL_APP_RUNTIME_MANIFEST_PATH',
    'LOCAL_BACKEND_HELPER_EXECUTABLE',
    'LOG_FILE_PATH',
  ]);
  assertNoUnresolvedPlaceholders(materializedConfig, [], overridableKeys);
  return materializedConfig;
}

function materializeLocalBackendRuntimeConfig(params) {
  const bundlePath = path.join(params.resourcesPath, LOCAL_BACKEND_RUNTIME_BUNDLE_FILENAME);
  if (!fs.existsSync(bundlePath)) {
    throw new Error(`Missing local backend runtime bundle: ${bundlePath}`);
  }

  const raw = readFileSyncWithInterruptedReadRetry(bundlePath, 'utf8');
  const parsed = JSON.parse(raw);
  assertLocalBackendRuntimeBundleKeys(parsed);
  const helperExecutablePath = path.join(
    params.resourcesPath,
    LOCAL_BACKEND_HELPER_EXECUTABLE_RELATIVE_PATH
  );
  const appRuntimeManifestPath = materializePackagedAppRuntimeManifest({
    resourcesPath: params.resourcesPath,
    userDataDir: params.userDataDir,
    helperExecutablePath,
  });
  const config = buildMaterializedLocalBackendRuntimeConfig(
    parsed,
    params.userDataDir,
    params.logsDir,
    params.resourcesPath,
    helperExecutablePath,
    appRuntimeManifestPath
  );
  const configPath = path.join(params.userDataDir, LOCAL_BACKEND_RUNTIME_CONFIG_FILENAME);
  writeJsonAtomically(configPath, config);
  return { bundlePath, configPath, config };
}

function materializeDevelopmentLocalBackendRuntimeConfig(params) {
  const { envPath, env } = readDevelopmentLocalBackendEnv(params.agentsRoot);
  const bundleConfig = buildLocalBackendRuntimeBundle(env);
  const appRuntimeManifestPath = materializeDevelopmentAppRuntimeManifest({
    agentsRoot: params.agentsRoot,
    userDataDir: params.userDataDir,
  });
  const config = buildMaterializedLocalBackendRuntimeConfig(
    bundleConfig,
    params.userDataDir,
    params.logsDir,
    '',
    null,
    appRuntimeManifestPath
  );
  const configPath = path.join(params.userDataDir, LOCAL_BACKEND_RUNTIME_CONFIG_FILENAME);
  writeJsonAtomically(configPath, config);
  return { sourceEnvPath: envPath, configPath, config };
}

module.exports = {
  DEV_LOCAL_BACKEND_ENV_FILE_ENV,
  LOCAL_BACKEND_RUNTIME_BUNDLE_FILENAME,
  LOCAL_BACKEND_RUNTIME_CONFIG_FILENAME,
  LOCAL_APP_RUNTIME_MANIFEST_FILENAME,
  resolveLoopbackBinding,
  buildLocalBackendControlSocketPath,
  buildLocalAppRuntimeManifestPath,
  readDevelopmentLocalBackendEnv,
  buildMaterializedLocalBackendRuntimeConfig,
  materializeLocalBackendRuntimeConfig,
  materializeDevelopmentLocalBackendRuntimeConfig,
  materializeDevelopmentAppRuntimeManifest,
  materializePackagedAppRuntimeManifest,
};
