const assert = require('assert');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { test } = require('node:test');

const {
  HELPER_RUNTIME_DIRNAME,
  HELPER_RUNTIME_MANIFEST_FILENAME,
  APP_RUNTIME_MANIFEST_FILENAME,
  PYTHON_VERSION,
  PYTHON_STANDALONE_RELEASE_TAG,
  PYTHON_STANDALONE_ARCHIVE_NAME,
  PYTHON_STANDALONE_ARCHIVE_URL,
  PYTHON_STANDALONE_ARCHIVE_SHA256,
  UV_EXPORT_ARGS,
  UV_BUILD_ARGS,
  BUNDLED_WORKSPACE_PACKAGES,
  WORKSPACE_WHEEL_PREFIXES,
  PIP_INSTALL_WHEEL_ARGS,
  VERIFY_MIGRATIONS_INLINE_SCRIPT,
  buildHelperRuntimePaths,
  copyExtractedRuntime,
  findRuntimeSymlinkPaths,
  prunePythonBytecode,
} = require('../scripts/prepare-local-backend-helper-runtime.js');

function makeTempDir(prefix) {
  return fs.mkdtempSync(path.join(os.tmpdir(), prefix));
}

test('helper runtime archive spec is pinned to a single bundled CPython release', () => {
  assert.equal(PYTHON_VERSION, '3.12.13');
  assert.equal(PYTHON_STANDALONE_RELEASE_TAG, '20260325');
  assert.equal(
    PYTHON_STANDALONE_ARCHIVE_NAME,
    'cpython-3.12.13+20260325-aarch64-apple-darwin-install_only_stripped.tar.gz'
  );
  assert.equal(
    PYTHON_STANDALONE_ARCHIVE_URL,
    'https://github.com/astral-sh/python-build-standalone/releases/download/20260325/' +
      'cpython-3.12.13%2B20260325-aarch64-apple-darwin-install_only_stripped.tar.gz'
  );
  assert.match(PYTHON_STANDALONE_ARCHIVE_SHA256, /^[0-9a-f]{64}$/);
});

test('helper runtime paths resolve to packaged resource locations', () => {
  const paths = buildHelperRuntimePaths();
  assert.equal(
    paths.helperRuntimeRoot,
    path.join(
      path.resolve(__dirname, '..'),
      '.cache',
      HELPER_RUNTIME_DIRNAME
    )
  );
  assert.equal(
    paths.helperRuntimeExecutable,
    path.join(paths.helperRuntimeRoot, 'bin', 'python3')
  );
  assert.equal(
    paths.helperRuntimeManifestPath,
    path.join(paths.helperRuntimeRoot, HELPER_RUNTIME_MANIFEST_FILENAME)
  );
  assert.equal(
    paths.appRuntimeManifestPath,
    path.join(paths.helperRuntimeRoot, APP_RUNTIME_MANIFEST_FILENAME)
  );
});

test('helper runtime exports only local backend dependencies from uv.lock', () => {
  assert.equal(UV_EXPORT_ARGS.includes('--extra'), false);
  assert.equal(UV_EXPORT_ARGS.includes('cloud_backend'), false);
  assert.equal(UV_EXPORT_ARGS.includes('pantaray-agents'), true);
});

test('helper runtime builds the local package before offline pip installation', () => {
  assert.equal(UV_EXPORT_ARGS.includes('--no-emit-workspace'), true);
  assert.deepEqual(UV_BUILD_ARGS, ['--quiet', 'build', '--wheel']);
  assert.deepEqual(BUNDLED_WORKSPACE_PACKAGES, ['pantaray-agents', 'pantaray-llm']);
  assert.deepEqual(WORKSPACE_WHEEL_PREFIXES, ['pantaray_agents-', 'pantaray_llm-']);
  assert.deepEqual(PIP_INSTALL_WHEEL_ARGS, ['-m', 'pip', 'install', '--no-index', '--no-deps']);
});

test('helper runtime verifies migrations and sqlite-vec after installation', () => {
  assert.match(
    VERIFY_MIGRATIONS_INLINE_SCRIPT,
    /load_default_migrations/
  );
  assert.match(
    VERIFY_MIGRATIONS_INLINE_SCRIPT,
    /0001_core_runtime\.sql/
  );
  assert.match(VERIFY_MIGRATIONS_INLINE_SCRIPT, /import sqlite_vec/);
  assert.match(VERIFY_MIGRATIONS_INLINE_SCRIPT, /import pypdfium2/);
  assert.match(VERIFY_MIGRATIONS_INLINE_SCRIPT, /enable_load_extension\(True\)/);
  assert.match(VERIFY_MIGRATIONS_INLINE_SCRIPT, /enable_load_extension\(False\)/);
  assert.match(VERIFY_MIGRATIONS_INLINE_SCRIPT, /vec_version\(\)/);
  assert.match(VERIFY_MIGRATIONS_INLINE_SCRIPT, /v0\.1\.9/);
  assert.match(VERIFY_MIGRATIONS_INLINE_SCRIPT, /DISTANCE_METRIC=cosine/);
  assert.match(VERIFY_MIGRATIONS_INLINE_SCRIPT, /embedding MATCH \?/);
});

test('copyExtractedRuntime materializes relative and absolute runtime symlinks', () => {
  const sourceRoot = path.join(makeTempDir('helper-runtime-source-'), 'python');
  const destinationRoot = path.join(makeTempDir('helper-runtime-destination-'), 'python');
  const binDir = path.join(sourceRoot, 'bin');
  const pkgconfigDir = path.join(sourceRoot, 'lib', 'pkgconfig');

  fs.mkdirSync(binDir, { recursive: true });
  fs.mkdirSync(pkgconfigDir, { recursive: true });
  fs.writeFileSync(path.join(binDir, 'python3.12'), 'python-binary', 'utf8');
  fs.writeFileSync(
    path.join(pkgconfigDir, 'python-3.12-embed.pc'),
    'pkg-config',
    'utf8'
  );
  fs.symlinkSync('python3.12', path.join(binDir, 'python3'));
  fs.symlinkSync(
    path.join(pkgconfigDir, 'python-3.12-embed.pc'),
    path.join(pkgconfigDir, 'python3-embed.pc')
  );

  copyExtractedRuntime(sourceRoot, destinationRoot);

  const pythonPath = path.join(destinationRoot, 'bin', 'python3');
  const pkgconfigPath = path.join(
    destinationRoot,
    'lib',
    'pkgconfig',
    'python3-embed.pc'
  );
  assert.equal(fs.lstatSync(pythonPath).isSymbolicLink(), false);
  assert.equal(fs.lstatSync(pkgconfigPath).isSymbolicLink(), false);
  assert.equal(fs.readFileSync(pythonPath, 'utf8'), 'python-binary');
  assert.equal(fs.readFileSync(pkgconfigPath, 'utf8'), 'pkg-config');
  assert.deepEqual(findRuntimeSymlinkPaths(destinationRoot), []);
});

test('copyExtractedRuntime rejects symlink targets outside the extracted runtime', () => {
  const sourceRoot = path.join(makeTempDir('helper-runtime-source-'), 'python');
  const destinationRoot = path.join(makeTempDir('helper-runtime-destination-'), 'python');
  const outsideFile = path.join(makeTempDir('helper-runtime-outside-'), 'outside.txt');

  fs.mkdirSync(path.join(sourceRoot, 'bin'), { recursive: true });
  fs.writeFileSync(path.join(sourceRoot, 'bin', 'python3'), 'python-binary', 'utf8');
  fs.writeFileSync(outsideFile, 'outside', 'utf8');
  fs.symlinkSync(outsideFile, path.join(sourceRoot, 'bin', 'outside-link'));

  assert.throws(
    () => copyExtractedRuntime(sourceRoot, destinationRoot),
    /escapes runtime root/
  );
});

test('copyExtractedRuntime rejects symlink loops explicitly', () => {
  const sourceRoot = path.join(makeTempDir('helper-runtime-source-'), 'python');
  const destinationRoot = path.join(makeTempDir('helper-runtime-destination-'), 'python');
  const loopDir = path.join(sourceRoot, 'lib', 'loop');

  fs.mkdirSync(path.join(sourceRoot, 'bin'), { recursive: true });
  fs.mkdirSync(loopDir, { recursive: true });
  fs.writeFileSync(path.join(sourceRoot, 'bin', 'python3'), 'python-binary', 'utf8');
  fs.symlinkSync('b', path.join(loopDir, 'a'));
  fs.symlinkSync('a', path.join(loopDir, 'b'));

  assert.throws(
    () => copyExtractedRuntime(sourceRoot, destinationRoot),
    /Detected symlink cycle/
  );
});

test('prunePythonBytecode removes pyc files and pycache directories', () => {
  const runtimeRoot = path.join(makeTempDir('helper-runtime-bytecode-'), 'python');
  const pycacheDir = path.join(
    runtimeRoot,
    'lib',
    'python3.12',
    'site-packages',
    'pkg',
    '__pycache__'
  );
  const loosePyc = path.join(runtimeRoot, 'lib', 'python3.12', 'loose.pyc');
  const sourceFile = path.join(runtimeRoot, 'lib', 'python3.12', 'module.py');

  fs.mkdirSync(pycacheDir, { recursive: true });
  fs.writeFileSync(path.join(pycacheDir, 'module.cpython-312.pyc'), 'bytecode', 'utf8');
  fs.writeFileSync(loosePyc, 'bytecode', 'utf8');
  fs.writeFileSync(sourceFile, 'source', 'utf8');

  const result = prunePythonBytecode(runtimeRoot);

  assert.deepEqual(result, {
    removedFileCount: 2,
    removedDirectoryCount: 1,
  });
  assert.equal(fs.existsSync(pycacheDir), false);
  assert.equal(fs.existsSync(loosePyc), false);
  assert.equal(fs.readFileSync(sourceFile, 'utf8'), 'source');
});

test('prunePythonBytecode rejects pycache symlinks', () => {
  const runtimeRoot = path.join(makeTempDir('helper-runtime-bytecode-'), 'python');
  const targetDir = path.join(runtimeRoot, 'target');
  const symlinkPath = path.join(runtimeRoot, '__pycache__');

  fs.mkdirSync(targetDir, { recursive: true });
  fs.symlinkSync('target', symlinkPath);

  assert.throws(
    () => prunePythonBytecode(runtimeRoot),
    /Cannot prune bytecode through helper runtime symlink/
  );
});
