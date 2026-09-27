const fs = require('fs');
const path = require('path');
const dotenv = require('dotenv');
const { isProductionDesktopBuild } = require('./runtime-build-env');
const {
  RUNTIME_MATERIALIZED_KEYS,
  buildLocalBackendRuntimeBundle,
} = require('../electron/local_backend_runtime_bundle.js');

const TARGET_PATH = path.resolve(
  __dirname,
  '..',
  'electron',
  'resources',
  'local_backend_runtime.bundle.json'
);
const AGENTS_DIR = path.resolve(__dirname, '..', '..', 'agents');
const PRODUCTION_LOCAL_BACKEND_ENV_PATH = path.join(
  AGENTS_DIR,
  '.env.local.backend.production'
);
const DEVELOPMENT_LOCAL_BACKEND_ENV_PATH = path.join(
  AGENTS_DIR,
  '.env.local.backend.local'
);

function resolveLocalBackendEnvPath() {
  return isProductionDesktopBuild()
    ? PRODUCTION_LOCAL_BACKEND_ENV_PATH
    : DEVELOPMENT_LOCAL_BACKEND_ENV_PATH;
}

function requireLocalBackendEnvPath() {
  const envPath = resolveLocalBackendEnvPath();
  if (!fs.existsSync(envPath)) {
    throw new Error(`Missing local backend env file: ${envPath}`);
  }
  return envPath;
}

function readLocalBackendEnv(envPath) {
  return dotenv.parse(fs.readFileSync(envPath, 'utf8'));
}

function main() {
  const sourceEnvPath = requireLocalBackendEnvPath();
  const bundle = buildLocalBackendRuntimeBundle(readLocalBackendEnv(sourceEnvPath), {
    releaseBuild: isProductionDesktopBuild(),
  });
  fs.mkdirSync(path.dirname(TARGET_PATH), { recursive: true });
  fs.writeFileSync(TARGET_PATH, `${JSON.stringify(bundle, null, 2)}\n`, {
    encoding: 'utf8',
    mode: 0o600,
  });
  process.stdout.write(`Generated local backend runtime bundle: ${TARGET_PATH}\n`);
}

if (require.main === module) {
  main();
}

module.exports = {
  TARGET_PATH,
  PRODUCTION_LOCAL_BACKEND_ENV_PATH,
  DEVELOPMENT_LOCAL_BACKEND_ENV_PATH,
  RUNTIME_MATERIALIZED_KEYS,
  resolveLocalBackendEnvPath,
  requireLocalBackendEnvPath,
  readLocalBackendEnv,
  buildLocalBackendRuntimeBundle,
  main,
};
