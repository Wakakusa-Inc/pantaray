/**
 * Electron 配布版向けの runtime_config.json を生成する。
 *
 * 背景（今回の「VITE_WEB_APP_URL があるのに Missing env になる」原因）:
 * - `pnpm run electron:build` は `vite build` の後に、別プロセスで
 *   `node scripts/generate-electron-runtime-config.js` を実行する。
 * - Vite が `.env.local` を読んでも、その値はシェル環境に export されないため、
 *   後続の node スクリプトからは見えない。
 *
 * 方針:
 * - 本スクリプトは Vite とは独立に `.env.*` を読み込む（dotenv）。
 * - CI もローカルと同じ設定ファイルを読む（既存の環境変数は上書きしない）。
 * - packaged build では `.env.production` を読み、electron dev では `.env.local` を読む。
 *
 * 入力（環境変数 or .env.*）:
 * - BACKEND_URL
 * - VITE_API_HOST
 * - VITE_WEB_APP_URL / VITE_SUPABASE_URL / VITE_SUPABASE_PUBLISHABLE_KEY
 *   （PANTARAY_ACCOUNT_LOGIN_ENABLED が true のときだけ）
 *
 * 出力:
 * - electron/runtime_config.json
 */

const fs = require('fs');
const path = require('path');
const {
  isCi,
  isProductionDesktopBuild,
  loadBuildEnvFiles,
  requireEnv,
} = require('./runtime-build-env');
const { parseLoopbackBackendUrl } = require('../electron/loopback_backend_url.js');
const { PANTARAY_ACCOUNT_LOGIN_ENABLED } = require('../electron/src/auth/accountLoginFeature.ts');

function normalizeOrigin(value) {
  const raw = String(value || '').trim();
  const u = new URL(raw);
  return u.origin;
}

function normalizeAbsoluteUrl(value) {
  const raw = String(value || '').trim();
  const u = new URL(raw);
  return u.toString().replace(/\/$/, '');
}

function buildAccountRuntimeConfig(env) {
  const webAppOrigin = normalizeOrigin(requireEnv(env, 'VITE_WEB_APP_URL'));
  const supabaseUrl = normalizeAbsoluteUrl(requireEnv(env, 'VITE_SUPABASE_URL'));
  const publishableKey = requireEnv(env, 'VITE_SUPABASE_PUBLISHABLE_KEY');
  // Security boundary checks for packaged desktop config.
  // ローカルの ad-hoc build でも packaged app は production runtime として動く。
  if (isProductionDesktopBuild(env) || isCi(env)) {
    if (!webAppOrigin.startsWith('https://')) {
      throw new Error('VITE_WEB_APP_URL must be https in packaged desktop builds.');
    }
    if (!supabaseUrl.startsWith('https://') || !/\.supabase\.co$/i.test(new URL(supabaseUrl).hostname)) {
      throw new Error('VITE_SUPABASE_URL must be https://*.supabase.co in packaged desktop builds.');
    }
  }
  return {
    web_app_origin: webAppOrigin,
    supabase_url: supabaseUrl,
    supabase_publishable_key: publishableKey,
  };
}

function buildRuntimeConfig(env, { accountLoginEnabled }) {
  const backendUrl = parseLoopbackBackendUrl(requireEnv(env, 'BACKEND_URL')).origin;
  const apiHostOrigin = normalizeOrigin(requireEnv(env, 'VITE_API_HOST'));
  // Renderer と main の許可先がズレるのを防ぐ（CSP allowlist と一致させる）
  if (apiHostOrigin !== new URL(backendUrl).origin) {
    throw new Error('VITE_API_HOST must match BACKEND_URL origin.');
  }

  return {
    ...(accountLoginEnabled ? buildAccountRuntimeConfig(env) : {}),
    backend_url: backendUrl,
    api_host_origin: apiHostOrigin,
  };
}

function main() {
  loadBuildEnvFiles(process.env);
  const out = buildRuntimeConfig(process.env, {
    accountLoginEnabled: PANTARAY_ACCOUNT_LOGIN_ENABLED,
  });
  const targetPath = path.join(__dirname, '..', 'electron', 'runtime_config.json');
  fs.writeFileSync(targetPath, `${JSON.stringify(out, null, 2)}\n`, { encoding: 'utf8', mode: 0o600 });
  process.stdout.write(`Generated runtime config: ${targetPath}\n`);
}

if (require.main === module) {
  main();
}

module.exports = { buildRuntimeConfig };
