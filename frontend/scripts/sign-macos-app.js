const path = require('path');

const {
  buildLocalBackendHelperSigningPlan,
  createLocalBackendHelperSigningIgnore,
  refreshSignedLocalBackendHelperManifest,
} = require('./macos-signing-targets.js');

const FRONTEND_ROOT = path.resolve(__dirname, '..');
const RELEASE_BUILD_FLAG = '1';
const AD_HOC_SIGNING_IDENTITY = '-';

function readEnv(env, name) {
  return String(env[name] || '').trim();
}

function resolveMacosSigningIdentity(env = process.env) {
  const isReleaseBuild = readEnv(env, 'PANTARAY_RELEASE_BUILD') === RELEASE_BUILD_FLAG;
  const hasSigningCertificate = Boolean(readEnv(env, 'CSC_NAME') || readEnv(env, 'CSC_LINK'));
  if (isReleaseBuild || hasSigningCertificate) return null;
  return AD_HOC_SIGNING_IDENTITY;
}

async function signMacosApp(options) {
  const signingPlan = buildLocalBackendHelperSigningPlan(options.app);
  const ignore = createLocalBackendHelperSigningIgnore({
    appPath: options.app,
    existingIgnore: options.ignore,
    signableFiles: signingPlan.signableFiles,
  });

  process.stdout.write(
    [
      '[sign-macos-app] local_backend_helper signing plan',
      `machO=${signingPlan.signableFiles.length}`,
      `ignored=${signingPlan.ignoredFiles.length}`,
      `root=${signingPlan.helperRoot}`,
    ].join(' ') + '\n'
  );

  const localSigningIdentity = resolveMacosSigningIdentity();
  if (localSigningIdentity) {
    process.stdout.write('[sign-macos-app] using ad-hoc identity for local macOS build\n');
  }

  const { signAsync } = loadElectronOsxSign();
  await signAsync({
    ...options,
    ...(localSigningIdentity ? { identity: localSigningIdentity } : {}),
    ignore,
    optionsForFile: buildOptionsForFile({
      appPath: options.app,
      existingOptionsForFile: options.optionsForFile,
    }),
  });
}

function buildOptionsForFile({ appPath, existingOptionsForFile }) {
  const resolvedAppPath = path.resolve(appPath);
  let helperManifestRefreshed = false;

  return (filePath) => {
    if (!helperManifestRefreshed && path.resolve(filePath) === resolvedAppPath) {
      helperManifestRefreshed = true;
      const result = refreshSignedLocalBackendHelperManifest(appPath);
      if (result.updated) {
        process.stdout.write(
          [
            '[sign-macos-app] refreshed signed local_backend_helper manifest',
            `python_sha256=${result.pythonSha256}`,
            `manifest=${result.manifestPath}`,
          ].join(' ') + '\n'
        );
      }
    }

    return typeof existingOptionsForFile === 'function'
      ? existingOptionsForFile(filePath)
      : undefined;
  };
}

function loadElectronOsxSign() {
  try {
    return require('@electron/osx-sign');
  } catch (error) {
    if (!error || error.code !== 'MODULE_NOT_FOUND') {
      throw error;
    }
    const electronBuilderPackagePath = require.resolve('electron-builder/package.json', {
      paths: [FRONTEND_ROOT],
    });
    const osxSignPath = require.resolve('@electron/osx-sign', {
      paths: [path.dirname(electronBuilderPackagePath)],
    });
    return require(osxSignPath);
  }
}

module.exports = signMacosApp;
module.exports.default = signMacosApp;
module.exports.buildOptionsForFile = buildOptionsForFile;
module.exports.resolveMacosSigningIdentity = resolveMacosSigningIdentity;
module.exports.loadElectronOsxSign = loadElectronOsxSign;
