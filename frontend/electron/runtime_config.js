/**
 * Electron(main) 用の実行時設定ローダー。
 *
 * 目的:
 * - 配布版は「実行時の env / .env を信頼しない」(改ざん可能性があるため)
 * - 必要な接続先（Backend と、アカウントログインが有効なときだけ Web/Supabase）はビルド時に生成した設定ファイルをSSOTとする
 * - ローカル開発時は従来通り process.env（dotenv 等）から読む
 *
 * 運用:
 * - 配布版: `electron/runtime_config.json` を同梱（asar内）
 * - 開発版: `runtime_config.json` が無ければ env から構築
 */

const fs = require('fs');
const path = require('path');
const { parseLoopbackBackendUrl } = require('./loopback_backend_url.js');

/**
 * The account fields exist exactly when account login is enabled
 * (`PANTARAY_ACCOUNT_LOGIN_ENABLED`); otherwise nothing reads them.
 *
 * @typedef {Object} ElectronRuntimeConfig
 * @property {string} [web_app_origin] - e.g. "https://your-frontend.web.app"
 * @property {string} [supabase_url] - e.g. "https://your-project.supabase.co"
 * @property {string} [supabase_publishable_key] - e.g. "sb_publishable_..."
 * @property {string} backend_url - e.g. "http://127.0.0.1:8005"
 * @property {string} api_host_origin - e.g. "https://your-backend-api.example.com" (renderer/main allowlist)
 */

const ACCOUNT_KEYS = ['web_app_origin', 'supabase_url', 'supabase_publishable_key'];

function normalizeOriginUrl(value) {
  const raw = String(value || '').trim();
  if (!raw) return '';
  try {
    const u = new URL(raw);
    return u.origin;
  } catch {
    return '';
  }
}

function normalizeAbsoluteUrl(value) {
  const raw = String(value || '').trim();
  if (!raw) return '';
  try {
    // accept full URL
    new URL(raw);
    return raw.replace(/\/$/, '');
  } catch {
    return '';
  }
}

function normalizeLoopbackBackendUrl(value) {
  return parseLoopbackBackendUrl(value).origin;
}

/**
 * @param {unknown} cfg
 * @param {boolean} accountLoginEnabled
 * @returns {cfg is ElectronRuntimeConfig}
 */
function isValidConfigShape(cfg, accountLoginEnabled) {
  if (!cfg || typeof cfg !== 'object') return false;
  const o = /** @type {Record<string, unknown>} */ (cfg);
  const keys = ['backend_url', 'api_host_origin', ...(accountLoginEnabled ? ACCOUNT_KEYS : [])];
  return keys.every((key) => typeof o[key] === 'string');
}

function normalizeAccountConfig({ webAppOrigin, supabaseUrl, publishableKey }) {
  return {
    web_app_origin: normalizeOriginUrl(webAppOrigin),
    supabase_url: normalizeAbsoluteUrl(supabaseUrl),
    supabase_publishable_key: String(publishableKey || '').trim(),
  };
}

/**
 * 設定をロードする。
 *
 * @param {Object} params
 * @param {boolean} params.isPackaged
 * @param {boolean} params.accountLoginEnabled
 * @returns {ElectronRuntimeConfig}
 */
function loadRuntimeConfig({ isPackaged, accountLoginEnabled }) {
  const configPath = path.join(__dirname, 'runtime_config.json');

  if (isPackaged && fs.existsSync(configPath)) {
    const raw = fs.readFileSync(configPath, 'utf8');
    const parsed = JSON.parse(raw);
    if (!isValidConfigShape(parsed, accountLoginEnabled)) {
      throw new Error('Invalid runtime_config.json schema.');
    }
    const account = accountLoginEnabled
      ? normalizeAccountConfig({
          webAppOrigin: parsed.web_app_origin,
          supabaseUrl: parsed.supabase_url,
          publishableKey: parsed.supabase_publishable_key,
        })
      : {};
    const backendUrl = normalizeLoopbackBackendUrl(parsed.backend_url);
    const apiHostOrigin = normalizeOriginUrl(parsed.api_host_origin);
    // 配布版は必須値が揃っていないと危険（接続先の曖昧さはトークン漏えいに繋がる）なので fail closed。
    if (!backendUrl || !apiHostOrigin || Object.values(account).some((value) => !value)) {
      throw new Error('runtime_config.json contains empty/invalid values.');
    }
    return { ...account, backend_url: backendUrl, api_host_origin: apiHostOrigin };
  }

  if (isPackaged) {
    // 配布版: env/.env を信頼しないため、設定ファイルが無い場合は fail closed。
    throw new Error('Missing runtime_config.json for packaged app.');
  }

  // dev: env を SSOT にする。runtime_config.json が存在しても使わない。
  const backendUrl = normalizeLoopbackBackendUrl(process.env.BACKEND_URL);
  const apiHostOrigin =
    normalizeOriginUrl(process.env.VITE_API_HOST) || normalizeOriginUrl(backendUrl);
  const account = accountLoginEnabled
    ? normalizeAccountConfig({
        webAppOrigin: process.env.VITE_WEB_APP_URL,
        supabaseUrl: process.env.VITE_SUPABASE_URL,
        publishableKey: process.env.VITE_SUPABASE_PUBLISHABLE_KEY,
      })
    : {};
  return { ...account, backend_url: backendUrl, api_host_origin: apiHostOrigin };
}

module.exports = { loadRuntimeConfig };
