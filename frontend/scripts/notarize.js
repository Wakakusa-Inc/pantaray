/**
 * electron-builder afterSign hook: macOS Notarization.
 *
 * 目的:
 * - CI（GitHub Actions）で desktop 配布物を build する際に、署名済みアプリを Apple へ Notarize する。
 * - secrets が未設定の環境（ローカル開発等）では安全にスキップする。
 *
 * 前提:
 * - APPLE_ID / APPLE_APP_SPECIFIC_PASSWORD / APPLE_TEAM_ID が設定されていること
 * - macOS runner であること（electronPlatformName === 'darwin'）
 */

const fs = require('fs');
const path = require('path');

console.log('[notarize] module loaded');

const RELEASE_BUILD_FLAG = '1';
const NOTARIZATION_ENV_NAMES = ['APPLE_ID', 'APPLE_APP_SPECIFIC_PASSWORD', 'APPLE_TEAM_ID'];
const NOTARIZATION_MAX_ATTEMPTS = 3;
const NOTARIZATION_INITIAL_RETRY_DELAY_MS = 15_000;
const NOTARIZATION_RETRY_DELAY_MULTIPLIER = 2;
const RETRYABLE_NOTARIZATION_ERROR_PATTERNS = [
  /abortedUpload/i,
  /connectTimeout/i,
  /connection timed out/i,
  /ECONNRESET/i,
  /ETIMEDOUT/i,
  /HTTPClientError/i,
  /network/i,
  /timeout/i,
];

function readEnv(env, name) {
  return String(env[name] || '').trim();
}

function isReleaseBuild(env) {
  return readEnv(env, 'PANTARAY_RELEASE_BUILD') === RELEASE_BUILD_FLAG;
}

function buildNotarizationEnv(env) {
  const values = {
    appleId: readEnv(env, 'APPLE_ID'),
    applePassword: readEnv(env, 'APPLE_APP_SPECIFIC_PASSWORD'),
    teamId: readEnv(env, 'APPLE_TEAM_ID'),
  };
  const missingNames = NOTARIZATION_ENV_NAMES.filter((name) => !readEnv(env, name));
  return { values, missingNames };
}

function getErrorText(error) {
  if (error instanceof Error) {
    return `${error.name}: ${error.message}\n${error.stack || ''}`;
  }
  return String(error);
}

function isRetryableNotarizationError(error) {
  const errorText = getErrorText(error);
  return RETRYABLE_NOTARIZATION_ERROR_PATTERNS.some((pattern) => pattern.test(errorText));
}

function wait(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function notarizeWithRetry(notarizeFn, options, logger = console, sleep = wait) {
  let delayMs = NOTARIZATION_INITIAL_RETRY_DELAY_MS;
  let lastError = null;

  for (let attempt = 1; attempt <= NOTARIZATION_MAX_ATTEMPTS; attempt += 1) {
    try {
      logger.log(`[notarize] attempt ${attempt}/${NOTARIZATION_MAX_ATTEMPTS}`);
      await notarizeFn(options);
      return;
    } catch (error) {
      lastError = error;
      const retryable = isRetryableNotarizationError(error);
      if (!retryable || attempt === NOTARIZATION_MAX_ATTEMPTS) {
        throw error;
      }

      logger.warn(
        `[notarize] transient failure; retrying in ${delayMs}ms (${attempt}/${NOTARIZATION_MAX_ATTEMPTS})`
      );
      await sleep(delayMs);
      delayMs *= NOTARIZATION_RETRY_DELAY_MULTIPLIER;
    }
  }

  throw lastError;
}

exports.default = async function notarizeHook(context) {
  const platform = context && context.electronPlatformName;
  console.log(`[notarize] hook invoked platform="${platform}"`);
  if (platform !== 'darwin') {
    console.log('[notarize] skipped: non-darwin platform');
    return;
  }

  const { values, missingNames } = buildNotarizationEnv(process.env);
  const { appleId, applePassword, teamId } = values;
  console.log(
    `[notarize] env present appleId=${Boolean(appleId)} teamId=${Boolean(teamId)} appPassword=${Boolean(applePassword)}`
  );
  if (missingNames.length > 0) {
    if (isReleaseBuild(process.env)) {
      throw new Error(
        `Notarization credentials are required for release macOS build: ${missingNames.join(', ')}.`
      );
    }

    // ローカル/未設定CIでは notarization を任意にし、開発用 build を維持する。
    console.log('[notarize] skipped: missing Apple credentials');
    return;
  }

  const appId = 'com.pantaray.app';
  const appName = context.packager.appInfo.productFilename;
  const appPath = path.join(context.appOutDir, `${appName}.app`);
  if (!fs.existsSync(appPath)) {
    throw new Error(`Notarization target not found: ${appPath}`);
  }

  // electron-builder の依存（または transitive）として存在する想定
  // もし無い場合は devDependencies へ明示追加してください。
  const { notarize } = require('@electron/notarize');

  // afterSign で失敗した場合はビルドを落として気付けるようにする（fail-closed）
  const startedAt = Date.now();
  console.log(`[notarize] start app="${appName}" path="${appPath}"`);
  await notarizeWithRetry(notarize, {
    appBundleId: appId,
    appPath,
    appleId,
    appleIdPassword: applePassword,
    teamId,
  });
  const durationSec = Math.round((Date.now() - startedAt) / 1000);
  console.log(`[notarize] done in ${durationSec}s`);
};

exports.buildNotarizationEnv = buildNotarizationEnv;
exports.isReleaseBuild = isReleaseBuild;
exports.isRetryableNotarizationError = isRetryableNotarizationError;
exports.notarizeWithRetry = notarizeWithRetry;
