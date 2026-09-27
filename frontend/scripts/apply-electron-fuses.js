/**
 * electron-builder afterPack hook: Electron Fuses 適用。
 *
 * 目的:
 * - electron-builder（dmg/zip 等）に Electron fuses を適用し、
 *   **asar 以外からのロード禁止** と **asar 整合性検証** を有効化する。
 * - 署名（codesign）より前に fuses を反映し、配布物の改ざん耐性を高める。
 *
 * エラー条件:
 * - 対象の実行ファイルが見つからない場合は例外を投げ、ビルドを fail-fast する。
 */

const fs = require('fs');
const path = require('path');
const { execFileSync } = require('child_process');

function ensureExists(p) {
  if (!p || typeof p !== 'string') return null;
  return fs.existsSync(p) ? p : null;
}

function hasSigningConfig() {
  // electron-builder の署名設定が入っている場合は、afterPack 後に正式な codesign が走る。
  // 未設定の場合、Fuse 適用で既存の署名（Electron Framework 等）が無効化され、
  // macOS が "Code Signature Invalid" で起動直後にプロセスを殺すことがある。
  const cscLink = String(process.env.CSC_LINK || '').trim();
  const cscName = String(process.env.CSC_NAME || '').trim();
  return Boolean(cscLink || cscName);
}

function isReleaseBuild() {
  return String(process.env.PANTARAY_RELEASE_BUILD || '').trim() === '1';
}

function codesignAdHoc(appPath) {
  // 署名なし（暫定）の場合でも、最低限「有効なコード署名」として整合させるため ad-hoc 署名する。
  // NOTE: これは信頼（Notarization/Developer ID）を付与するものではない。
  // Fail-fast: 失敗したらビルドを落として原因を明確化する。
  execFileSync('codesign', ['--force', '--deep', '--sign', '-', appPath], { stdio: 'inherit' });
  execFileSync('codesign', ['--verify', '--deep', '--strict', '--verbose=2', appPath], {
    stdio: 'inherit',
  });
}

/**
 * electron-builder の afterPack hook。
 *
 * @param {any} context
 * @returns {Promise<void>}
 */
exports.default = async function applyFusesAfterPack(context) {
  const { flipFuses, FuseV1Options, FuseVersion } = require('@electron/fuses');

  const platform = context?.electronPlatformName;
  const appOutDir = context?.appOutDir;
  const appName = context?.packager?.appInfo?.productFilename;

  if (!platform || !appOutDir || !appName) {
    throw new Error(
      `apply-electron-fuses: invalid context (platform/appOutDir/appName missing). platform=${String(platform)}`
    );
  }

  /** @type {string | null} */
  let targetExecutable = null;

  if (platform === 'darwin') {
    const appPath = path.join(appOutDir, `${appName}.app`);
    targetExecutable = ensureExists(path.join(appPath, 'Contents', 'MacOS', appName));
  } else if (platform === 'win32') {
    targetExecutable = ensureExists(path.join(appOutDir, `${appName}.exe`));
  } else if (platform === 'linux') {
    targetExecutable = ensureExists(path.join(appOutDir, appName));
  } else {
    // 未知のプラットフォームは何もしない（必要になったら追加）
    return;
  }

  if (!targetExecutable) {
    throw new Error(
      `apply-electron-fuses: target executable not found. platform=${platform} appOutDir=${appOutDir}`
    );
  }

  // 配布物をasarのみから起動し、asar整合性検証を有効化する。
  await flipFuses(targetExecutable, {
    version: FuseVersion.V1,
    [FuseV1Options.RunAsNode]: false,
    [FuseV1Options.EnableCookieEncryption]: true,
    [FuseV1Options.EnableNodeOptionsEnvironmentVariable]: false,
    [FuseV1Options.EnableNodeCliInspectArguments]: false,
    [FuseV1Options.EnableEmbeddedAsarIntegrityValidation]: true,
    [FuseV1Options.OnlyLoadAppFromAsar]: true,
  });

  // macOS: 署名設定が無い場合は ad-hoc で再署名して "Code Signature Invalid" を回避する
  // （Developer ID / Notarization が揃うまでの暫定措置）
  if (platform === 'darwin' && !hasSigningConfig()) {
    if (isReleaseBuild()) {
      throw new Error(
        'apply-electron-fuses: release macOS build requires Developer ID signing config; refusing ad-hoc signing.'
      );
    }

    const appPath = path.join(appOutDir, `${appName}.app`);
    codesignAdHoc(appPath);
  }
};
