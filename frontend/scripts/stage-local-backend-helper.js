const fs = require('fs');
const path = require('path');
const {
  assertNoRuntimeSymlinks,
} = require('./prepare-local-backend-helper-runtime.js');

const FRONTEND_DIR = path.resolve(__dirname, '..');
const HELPER_SOURCE_DIR = path.join(
  FRONTEND_DIR,
  '.cache',
  'local_backend_helper'
);
const HELPER_STAGING_DIR = path.join(
  FRONTEND_DIR,
  '.generated',
  'local_backend_helper'
);

function assertDirectoryExists(directoryPath) {
  if (!fs.existsSync(directoryPath)) {
    throw new Error(`Missing local backend helper runtime: ${directoryPath}`);
  }
  if (!fs.statSync(directoryPath).isDirectory()) {
    throw new Error(`Local backend helper runtime is not a directory: ${directoryPath}`);
  }
}

function stageLocalBackendHelper({
  sourceDir = HELPER_SOURCE_DIR,
  stagingDir = HELPER_STAGING_DIR,
} = {}) {
  assertDirectoryExists(sourceDir);
  fs.rmSync(stagingDir, { recursive: true, force: true });
  fs.mkdirSync(path.dirname(stagingDir), { recursive: true });
  fs.cpSync(sourceDir, stagingDir, { recursive: true });
  assertNoRuntimeSymlinks(stagingDir);
  return stagingDir;
}

function main() {
  const stagedPath = stageLocalBackendHelper();
  process.stdout.write(`Staged local backend helper runtime: ${stagedPath}\n`);
}

if (require.main === module) {
  main();
}

module.exports = {
  HELPER_SOURCE_DIR,
  HELPER_STAGING_DIR,
  stageLocalBackendHelper,
};
