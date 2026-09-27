const assert = require('assert');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { test } = require('node:test');

const {
  stageLocalBackendHelper,
} = require('../scripts/stage-local-backend-helper.js');

function makeTempDir(prefix) {
  return fs.mkdtempSync(path.join(os.tmpdir(), prefix));
}

test('stageLocalBackendHelper copies the helper runtime into a clean staging directory', () => {
  const sourceDir = path.join(makeTempDir('helper-source-'), 'local_backend_helper');
  const stagingRoot = makeTempDir('helper-stage-');
  const stagingDir = path.join(stagingRoot, 'local_backend_helper');

  fs.mkdirSync(path.join(sourceDir, 'bin'), { recursive: true });
  fs.writeFileSync(path.join(sourceDir, 'bin', 'python3'), 'python-binary', 'utf8');
  fs.mkdirSync(stagingDir, { recursive: true });
  fs.writeFileSync(path.join(stagingDir, 'stale.txt'), 'stale', 'utf8');

  const result = stageLocalBackendHelper({ sourceDir, stagingDir });

  assert.equal(result, stagingDir);
  assert.equal(
    fs.readFileSync(path.join(stagingDir, 'bin', 'python3'), 'utf8'),
    'python-binary'
  );
  assert.equal(fs.existsSync(path.join(stagingDir, 'stale.txt')), false);
});

test('stageLocalBackendHelper fails closed when the source runtime is missing', () => {
  const sourceDir = path.join(makeTempDir('missing-helper-source-'), 'local_backend_helper');
  const stagingDir = path.join(makeTempDir('missing-helper-stage-'), 'local_backend_helper');

  assert.throws(
    () => stageLocalBackendHelper({ sourceDir, stagingDir }),
    /Missing local backend helper runtime/
  );
});

test('stageLocalBackendHelper fails closed when staged runtime contains symlinks', () => {
  const sourceDir = path.join(makeTempDir('helper-source-symlink-'), 'local_backend_helper');
  const stagingDir = path.join(makeTempDir('helper-stage-symlink-'), 'local_backend_helper');

  fs.mkdirSync(path.join(sourceDir, 'bin'), { recursive: true });
  fs.writeFileSync(path.join(sourceDir, 'bin', 'python3.12'), 'python-binary', 'utf8');
  fs.symlinkSync('python3.12', path.join(sourceDir, 'bin', 'python3'));

  assert.throws(
    () => stageLocalBackendHelper({ sourceDir, stagingDir }),
    /must not contain symlinks/
  );
});
