/**
 * Electron(main) 用の実行時設定ローダー。
 *
 * 目的:
 * - 配布版は「実行時の env / .env を信頼しない」(改ざん可能性があるため)
 * - 必要な接続先（Web/Supabase/Backend）はビルド時に生成した設定ファイルをSSOTとする
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
 * @typedef {Object} ElectronRuntimeConfig
 * @property {string} web_app_origin - e.g. "https://your-frontend.web.app"
 * @property {string} supabase_url - e.g. "https://your-project.supabase.co"
 * @property {string} supabase_publishable_key - e.g. "sb_publishable_..."
 * @property {string} backend_url - e.g. "http://127.0.0.1:8005"
 * @property {string} api_host_origin - e.g. "https://your-backend-api.example.com" (renderer/main allowlist)
 */

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
 * @returns {cfg is ElectronRuntimeConfig}
 */
function isValidConfigShape(cfg) {
  if (!cfg || typeof cfg !== 'object') return false;
  const o = /** @type {Record<string, unknown>} */ (cfg);
  return (
    typeof o.web_app_origin === 'string' &&
    typeof o.supabase_url === 'string' &&
    typeof o.supabase_publishable_key === 'string' &&
    typeof o.backend_url === 'string' &&
    typeof o.api_host_origin === 'string'
  );
}

/**
 * 設定をロードする。
 *
 * @param {Object} params
 * @param {boolean} params.isPackaged
 * @returns {ElectronRuntimeConfig}
 */
function loadRuntimeConfig({ isPackaged }) {
  const configPath = path.join(__dirname, 'runtime_config.json');

  if (isPackaged && fs.existsSync(configPath)) {
    const raw = fs.readFileSync(configPath, 'utf8');
    const parsed = JSON.parse(raw);
    if (!isValidConfigShape(parsed)) {
      throw new Error('Invalid runtime_config.json schema.');
    }
    // normalize
    const webAppOrigin = normalizeOriginUrl(parsed.web_app_origin);
    const supabaseUrl = normalizeAbsoluteUrl(parsed.supabase_url);
    const backendUrl = normalizeLoopbackBackendUrl(parsed.backend_url);
    const apiHostOrigin = normalizeOriginUrl(parsed.api_host_origin);
    const publishableKey = String(parsed.supabase_publishable_key || '').trim();
    // 配布版は必須値が揃っていないと危険（接続先の曖昧さはトークン漏えいに繋がる）なので fail closed。
    if (
      isPackaged &&
      (!webAppOrigin ||
        !supabaseUrl ||
        !backendUrl ||
        !apiHostOrigin ||
        !publishableKey)
    ) {
      throw new Error('runtime_config.json contains empty/invalid values.');
    }
    return {
      web_app_origin: webAppOrigin,
      supabase_url: supabaseUrl,
      supabase_publishable_key: publishableKey,
      backend_url: backendUrl,
      api_host_origin: apiHostOrigin,
    };
  }

  if (isPackaged) {
    // 配布版: env/.env を信頼しないため、設定ファイルが無い場合は fail closed。
    throw new Error('Missing runtime_config.json for packaged app.');
  }

  // dev: env を SSOT にする。runtime_config.json が存在しても使わない。
  const webAppOrigin = normalizeOriginUrl(process.env.VITE_WEB_APP_URL);
  const supabaseUrl = normalizeAbsoluteUrl(process.env.VITE_SUPABASE_URL);
  const backendUrl = normalizeLoopbackBackendUrl(process.env.BACKEND_URL);
  const apiHostOrigin =
    normalizeOriginUrl(process.env.VITE_API_HOST) || normalizeOriginUrl(backendUrl);
  const publishableKey = String(process.env.VITE_SUPABASE_PUBLISHABLE_KEY || '').trim();
  return {
    web_app_origin: webAppOrigin,
    supabase_url: supabaseUrl,
    supabase_publishable_key: publishableKey,
    backend_url: backendUrl,
    api_host_origin: apiHostOrigin,
  };
}

module.exports = { loadRuntimeConfig };
