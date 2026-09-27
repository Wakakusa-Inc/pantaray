const fs = require('fs');
const path = require('path');
const dotenv = require('dotenv');

const BUILD_ENV_KEY = 'PANTARAY_DESKTOP_BUILD_ENV';
const LOCAL_BUILD_ENV = 'local';
const PRODUCTION_BUILD_ENV = 'production';
const RELEASE_BUILD_FLAG = '1';

function readEnv(env, name) {
  return String(env[name] || '').trim();
}

function isCi(env = process.env) {
  const ci = readEnv(env, 'CI').toLowerCase();
  if (ci === '1' || ci === 'true') return true;
  return readEnv(env, 'GITHUB_ACTIONS').toLowerCase() === 'true';
}

function isReleaseBuild(env = process.env) {
  return (
    Boolean(readEnv(env, 'PANTARAY_DESKTOP_VERSION')) ||
    readEnv(env, 'PANTARAY_RELEASE_BUILD') === RELEASE_BUILD_FLAG
  );
}

function resolveDesktopBuildEnv(env = process.env) {
  const explicit = readEnv(env, BUILD_ENV_KEY).toLowerCase();
  const release = isReleaseBuild(env);
  if (explicit) {
    if (explicit !== LOCAL_BUILD_ENV && explicit !== PRODUCTION_BUILD_ENV) {
      throw new Error(`${BUILD_ENV_KEY} must be "${LOCAL_BUILD_ENV}" or "${PRODUCTION_BUILD_ENV}".`);
    }
    if (release && explicit === LOCAL_BUILD_ENV) {
      throw new Error(`${BUILD_ENV_KEY} cannot be "${LOCAL_BUILD_ENV}" in release builds.`);
    }
    return explicit;
  }
  return release ? PRODUCTION_BUILD_ENV : LOCAL_BUILD_ENV;
}

function isProductionDesktopBuild(env = process.env) {
  return resolveDesktopBuildEnv(env) === PRODUCTION_BUILD_ENV;
}

function loadBuildEnvFiles(env = process.env) {
  const candidates = isProductionDesktopBuild(env) ? ['.env.production'] : ['.env.local'];
  for (const name of candidates) {
    const envPath = path.join(__dirname, '..', name);
    if (fs.existsSync(envPath)) {
      dotenv.config({ path: envPath, override: false });
    }
  }
}

function requireEnv(env, name) {
  const value = String(env[name] || '').trim();
  if (!value) {
    const envFileHint = isProductionDesktopBuild(env)
      ? 'frontend/.env.production'
      : 'frontend/.env.local';
    throw new Error(
      [
        `Missing env: ${name}`,
        '',
        'ヒント:',
        `- \`${envFileHint}\` に設定している場合でも、このスクリプトは別プロセスで動くため dotenv で読み込みます。`,
        `- それでも見つからない場合は、\`${envFileHint}\` の場所/キー名を確認してください。`,
      ].join('\n')
    );
  }
  return value;
}

module.exports = {
  BUILD_ENV_KEY,
  LOCAL_BUILD_ENV,
  PRODUCTION_BUILD_ENV,
  isCi,
  isReleaseBuild,
  resolveDesktopBuildEnv,
  isProductionDesktopBuild,
  loadBuildEnvFiles,
  requireEnv,
};
