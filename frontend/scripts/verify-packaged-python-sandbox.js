const fs = require('fs');
const path = require('path');
const { execFileSync } = require('child_process');

const {
  HELPER_RUNTIME_DIRNAME,
  VERIFY_MIGRATIONS_INLINE_SCRIPT,
} = require('./prepare-local-backend-helper-runtime.js');
const {
  LOCAL_EMBEDDING_MODEL_DIRNAME,
} = require('../electron/local_backend_runtime_bundle.js');

const PYTHON_EXECUTABLE_RELATIVE_PATH = path.join(
  HELPER_RUNTIME_DIRNAME,
  'bin',
  'python3'
);
const PACKAGED_RESOURCES_ENV_NAME = 'PANTARAY_PACKAGED_RESOURCES_PATH';
// The digests in `electron/embedding_model_release.json` say the bundled files
// are the ones that were prepared; only loading them in the runtime that ships
// says this machine can run them. A refusal at startup is silent -- semantic
// memory search simply reports itself unavailable -- so the release has to fail
// here instead.
const VERIFY_EMBEDDING_MODEL_INLINE_SCRIPT = `
from pantaray_agents.local_runtime.embedding_local import load_local_embedding_model

model = load_local_embedding_model()
manifest = model.manifest
width = len(model.embed_query('パンタレイの意味検索'))
assert width == manifest.dimensions, (width, manifest.dimensions)

print(f'local embedding model verified: {manifest.profile_id}')
`.trim();

function readPackagedResourcesPath() {
  const value = String(process.env[PACKAGED_RESOURCES_ENV_NAME] || '').trim();
  if (!value) {
    throw new Error(`${PACKAGED_RESOURCES_ENV_NAME} is required.`);
  }
  return path.resolve(value);
}

function requireExistingPath(targetPath) {
  if (!fs.existsSync(targetPath)) {
    throw new Error(`Missing required packaged resource: ${targetPath}`);
  }
}

function verifyPackagedPythonSandbox() {
  const resourcesPath = readPackagedResourcesPath();
  const helperExecutable = path.join(
    resourcesPath,
    PYTHON_EXECUTABLE_RELATIVE_PATH
  );
  requireExistingPath(resourcesPath);
  requireExistingPath(helperExecutable);

  execFileSync(helperExecutable, ['-I', '-c', VERIFY_MIGRATIONS_INLINE_SCRIPT], {
    stdio: 'inherit',
    env: {
      ...process.env,
      PYTHONNOUSERSITE: '1',
    },
  });
  execFileSync(
    helperExecutable,
    ['-I', path.join(__dirname, 'verify-command-sandbox.py')],
    { stdio: 'inherit' }
  );
  execFileSync(
    helperExecutable,
    ['-I', '-c', VERIFY_EMBEDDING_MODEL_INLINE_SCRIPT],
    {
      stdio: 'inherit',
      env: {
        ...process.env,
        PYTHONNOUSERSITE: '1',
        LOCAL_EMBEDDING_MODEL_DIR: path.join(resourcesPath, LOCAL_EMBEDDING_MODEL_DIRNAME),
      },
    }
  );
}

if (require.main === module) {
  try {
    verifyPackagedPythonSandbox();
  } catch (error) {
    console.error(String(error && error.stack ? error.stack : error));
    process.exitCode = 1;
  }
}

module.exports = {
  PACKAGED_RESOURCES_ENV_NAME,
  PYTHON_EXECUTABLE_RELATIVE_PATH,
  verifyPackagedPythonSandbox,
};
