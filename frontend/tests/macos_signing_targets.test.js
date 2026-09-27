const assert = require('assert');
const crypto = require('crypto');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { test } = require('node:test');

const {
  HELPER_RUNTIME_RESOURCE_PATH,
  buildLocalBackendHelperSigningPlan,
  createLocalBackendHelperSigningIgnore,
  getLocalBackendHelperRoot,
  isMachOFile,
  refreshSignedLocalBackendHelperManifest,
} = require('../scripts/macos-signing-targets.js');
const {
  buildOptionsForFile,
  loadElectronOsxSign,
  resolveMacosSigningIdentity,
} = require('../scripts/sign-macos-app.js');

function makeTempDir(prefix) {
  return fs.mkdtempSync(path.join(os.tmpdir(), prefix));
}

function makeAppRoot() {
  return path.join(makeTempDir('macos-signing-app-'), 'Pantaray.app');
}

function writeFile(filePath, bytes) {
  fs.mkdirSync(path.dirname(filePath), { recursive: true });
  fs.writeFileSync(filePath, bytes);
}

function sha256Text(value) {
  return crypto.createHash('sha256').update(value).digest('hex');
}

test('getLocalBackendHelperRoot resolves the packaged helper resource path', () => {
  const appPath = makeAppRoot();
  assert.equal(
    getLocalBackendHelperRoot(appPath),
    path.join(appPath, HELPER_RUNTIME_RESOURCE_PATH)
  );
});

test('isMachOFile detects Mach-O and fat Mach-O magic values only', () => {
  const root = makeTempDir('macos-signing-magic-');
  const machO = path.join(root, 'python3');
  const fatMachO = path.join(root, 'universal');
  const littleEndianFatMachO = path.join(root, 'universal-le');
  const pyc = path.join(root, 'module.pyc');
  const javaClass = path.join(root, 'Example.class');
  const invalidFatMachO = path.join(root, 'empty-universal');

  writeFile(machO, Buffer.from('feedfacf00000000', 'hex'));
  writeFile(fatMachO, Buffer.from('cafebabe00000002', 'hex'));
  writeFile(littleEndianFatMachO, Buffer.from('bebafeca02000000', 'hex'));
  writeFile(pyc, Buffer.from('cb0d0d0a00000000', 'hex'));
  writeFile(javaClass, Buffer.from('cafebabe00000034', 'hex'));
  writeFile(invalidFatMachO, Buffer.from('cafebabe00000000', 'hex'));

  assert.equal(isMachOFile(machO), true);
  assert.equal(isMachOFile(fatMachO), true);
  assert.equal(isMachOFile(littleEndianFatMachO), true);
  assert.equal(isMachOFile(pyc), false);
  assert.equal(isMachOFile(javaClass), false);
  assert.equal(isMachOFile(invalidFatMachO), false);
});

test('buildLocalBackendHelperSigningPlan signs only Mach-O files in helper runtime', () => {
  const appPath = makeAppRoot();
  const helperRoot = getLocalBackendHelperRoot(appPath);
  const pythonBinary = path.join(helperRoot, 'bin', 'python3');
  const extensionModule = path.join(helperRoot, 'lib', 'module.so');
  const pycFile = path.join(helperRoot, 'lib', '__pycache__', 'module.pyc');
  const metadataFile = path.join(helperRoot, 'lib', 'pkgconfig', 'python3.pc');

  writeFile(pythonBinary, Buffer.from('feedfacf00000000', 'hex'));
  writeFile(extensionModule, Buffer.from('cffaedfe00000000', 'hex'));
  writeFile(pycFile, Buffer.from('cb0d0d0a00000000', 'hex'));
  writeFile(metadataFile, Buffer.from('prefix=/tmp/python\n', 'utf8'));

  const plan = buildLocalBackendHelperSigningPlan(appPath);

  assert.deepEqual(plan.signableFiles, [pythonBinary, extensionModule].sort());
  assert.deepEqual(plan.ignoredFiles, [metadataFile, pycFile].sort());
});

test('helper signing ignore preserves existing ignores and skips non-Mach-O helper files', () => {
  const appPath = makeAppRoot();
  const helperRoot = getLocalBackendHelperRoot(appPath);
  const pythonBinary = path.join(helperRoot, 'bin', 'python3');
  const pycFile = path.join(helperRoot, 'lib', '__pycache__', 'module.pyc');
  const appFile = path.join(appPath, 'Contents', 'Resources', 'app.asar');
  const existingIgnoredFile = path.join(appPath, 'Contents', 'Resources', 'skip.bin');

  writeFile(pythonBinary, Buffer.from('feedfacf00000000', 'hex'));
  writeFile(pycFile, Buffer.from('cb0d0d0a00000000', 'hex'));
  writeFile(appFile, Buffer.from('asar', 'utf8'));
  writeFile(existingIgnoredFile, Buffer.from('skip', 'utf8'));

  const plan = buildLocalBackendHelperSigningPlan(appPath);
  const ignore = createLocalBackendHelperSigningIgnore({
    appPath,
    existingIgnore: (filePath) => filePath === existingIgnoredFile,
    signableFiles: plan.signableFiles,
  });

  assert.equal(ignore(pythonBinary), false);
  assert.equal(ignore(pycFile), true);
  assert.equal(ignore(appFile), false);
  assert.equal(ignore(existingIgnoredFile), true);
});

test('helper signing plan rejects helper runtime symlinks', () => {
  const appPath = makeAppRoot();
  const helperRoot = getLocalBackendHelperRoot(appPath);
  const target = path.join(helperRoot, 'bin', 'python3.12');
  const link = path.join(helperRoot, 'bin', 'python3');

  writeFile(target, Buffer.from('feedfacf00000000', 'hex'));
  fs.symlinkSync('python3.12', link);

  assert.throws(
    () => buildLocalBackendHelperSigningPlan(appPath),
    /does not allow helper runtime symlinks/
  );
});

test('refreshSignedLocalBackendHelperManifest records the packaged signed python hash', () => {
  const appPath = makeAppRoot();
  const helperRoot = getLocalBackendHelperRoot(appPath);
  const pythonBinary = path.join(helperRoot, 'bin', 'python3');
  const manifestPath = path.join(helperRoot, 'runtime-manifest.json');

  writeFile(pythonBinary, 'signed-python');
  writeFile(
    manifestPath,
    `${JSON.stringify(
      {
        python_version: '3.12.13',
        python_executable_relative_path: path.join('bin', 'python3'),
        python_executable_sha256: 'pre-sign-hash',
      },
      null,
      2
    )}\n`
  );

  const result = refreshSignedLocalBackendHelperManifest(appPath);
  const manifest = JSON.parse(fs.readFileSync(manifestPath, 'utf8'));

  assert.equal(result.updated, true);
  assert.equal(manifest.python_executable_sha256, sha256Text('signed-python'));
});

test('sign-macos-app refreshes helper manifest immediately before signing the app bundle', () => {
  const appPath = makeAppRoot();
  const helperRoot = getLocalBackendHelperRoot(appPath);
  const pythonBinary = path.join(helperRoot, 'bin', 'python3');
  const manifestPath = path.join(helperRoot, 'runtime-manifest.json');
  const calls = [];

  writeFile(pythonBinary, 'signed-python');
  writeFile(
    manifestPath,
    `${JSON.stringify(
      {
        python_version: '3.12.13',
        python_executable_relative_path: path.join('bin', 'python3'),
        python_executable_sha256: 'pre-sign-hash',
      },
      null,
      2
    )}\n`
  );

  const optionsForFile = buildOptionsForFile({
    appPath,
    existingOptionsForFile(filePath) {
      calls.push(filePath);
      return { hardenedRuntime: true };
    },
  });

  assert.deepEqual(optionsForFile(path.join(helperRoot, 'lib', 'module.so')), {
    hardenedRuntime: true,
  });
  const beforeAppSignOptions = optionsForFile(appPath);
  const manifest = JSON.parse(fs.readFileSync(manifestPath, 'utf8'));

  assert.deepEqual(beforeAppSignOptions, { hardenedRuntime: true });
  assert.deepEqual(calls, [path.join(helperRoot, 'lib', 'module.so'), appPath]);
  assert.equal(manifest.python_executable_sha256, sha256Text('signed-python'));
});

test('sign-macos-app uses ad-hoc identity only for local unsigned builds', () => {
  assert.equal(resolveMacosSigningIdentity({}), '-');
  assert.equal(
    resolveMacosSigningIdentity({ CSC_NAME: '0123456789ABCDEF0123456789ABCDEF01234567' }),
    null
  );
  assert.equal(resolveMacosSigningIdentity({ CSC_LINK: '/tmp/cert.p12' }), null);
  assert.equal(resolveMacosSigningIdentity({ PANTARAY_RELEASE_BUILD: '1' }), null);
});

test('sign-macos-app can load electron osx signer from electron-builder dependencies', () => {
  const osxSign = loadElectronOsxSign();
  assert.equal(typeof osxSign.signAsync, 'function');
});
