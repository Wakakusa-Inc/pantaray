/**
 * macOS 署名付きビルドの前提条件チェック（fail-closed）。
 *
 * 目的:
 * - ローカルでも Developer ID 署名（Apple Developer）を必ず有効にしたい場合に、
 *   設定漏れ（ad-hoc / unsigned）でビルドが通ってしまう事故を防ぐ。
 *
 * 仕様:
 * - macOS 以外では何もしない（exit 0）
 * - macOS では次のいずれかが必須:
 *   - CSC_NAME が設定されている（Keychain に入っている証明書名で署名）
 *   - CSC_LINK + CSC_KEY_PASSWORD が設定されている（p12 を使って署名）
 * - PANTARAY_RELEASE_BUILD=1 の macOS build では notarization credentials も必須
 */

const RELEASE_BUILD_FLAG = '1';
const NOTARIZATION_ENV_NAMES = ['APPLE_ID', 'APPLE_APP_SPECIFIC_PASSWORD', 'APPLE_TEAM_ID'];

function readEnv(env, name) {
  return String(env[name] || '').trim();
}

function fail(msg) {
  process.stderr.write(`\n[require-macos-signing-env] ${msg}\n\n`);
  process.exit(1);
}

function isReleaseBuild(env) {
  return readEnv(env, 'PANTARAY_RELEASE_BUILD') === RELEASE_BUILD_FLAG;
}

function buildSigningEnvValidation({ platform, env }) {
  if (platform !== 'darwin') {
    return { ok: true };
  }

  const cscName = readEnv(env, 'CSC_NAME');
  const cscLink = readEnv(env, 'CSC_LINK');
  const cscKeyPassword = readEnv(env, 'CSC_KEY_PASSWORD');

  if (!cscName) {
    if (!cscLink) {
      return { ok: false, message: 'CSC_NAME or CSC_LINK is required for signed macOS build.' };
    }

    if (!cscKeyPassword) {
      return { ok: false, message: 'CSC_KEY_PASSWORD is required when using CSC_LINK.' };
    }
  }

  if (isReleaseBuild(env)) {
    const missingNotarizationEnvNames = NOTARIZATION_ENV_NAMES.filter(
      (name) => !readEnv(env, name)
    );
    if (missingNotarizationEnvNames.length > 0) {
      return {
        ok: false,
        message: `Notarization credentials are required for release macOS build: ${missingNotarizationEnvNames.join(', ')}.`,
      };
    }
  }

  return { ok: true };
}

function validateSigningEnvOrExit({ platform = process.platform, env = process.env } = {}) {
  const result = buildSigningEnvValidation({ platform, env });
  if (!result.ok) {
    fail(result.message);
  }
}

if (require.main === module) {
  validateSigningEnvOrExit();
}

module.exports = {
  buildSigningEnvValidation,
  isReleaseBuild,
};
