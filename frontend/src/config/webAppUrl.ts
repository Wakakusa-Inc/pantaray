/**
 * Web版（Firebase Hosting）に遷移するためのURLユーティリティ。
 *
 * なぜ必要か:
 * - Electron から外部ブラウザを開く/Browserログインへ誘導する際に、URLを直書きすると
 *   環境（preview/stg/prod）切替やドメイン変更に弱くなるため。
 *
 * 方針:
 * - `VITE_WEB_APP_URL` を参照する（環境差分で静かに誤動作するのを防ぐためフォールバックは持たない）。
 * - Electron（file://）実行時は window.location.origin が使えないため、環境変数が推奨。
 * - Web側はクリーンURL（`/login` 等）を採用する。
 */

export type WebAppRoute = 'login' | 'signup' | 'forgot-password';

export function getWebAppOrigin(): string {
  const fromWeb = (import.meta.env.VITE_WEB_APP_URL || '').trim();
  if (fromWeb) return fromWeb.replace(/\/$/, '');

  // フォールバックは持たない（環境差分で静かに誤動作するのを防ぐ）
  throw new Error('WebアプリURLが未設定です。`VITE_WEB_APP_URL` を設定してください。');
}

/**
 * WebアプリのURLを組み立てる。
 */
export function buildWebAppUrl(route: WebAppRoute, params?: Record<string, string>): string {
  const origin = getWebAppOrigin();
  const qs = new URLSearchParams(params || {});
  const query = qs.toString();
  return `${origin}/${route}${query ? `?${query}` : ''}`;
}
