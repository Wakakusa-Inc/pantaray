/**
 * JWT ユーティリティ（最小）
 *
 * 目的:
 * - Electron(main) で必要な最小限の JWT 解析（user_id/sub 抽出）を共通化する。
 * - renderer にはトークンを渡さない前提のため、ここは main 専用の補助関数とする。
 *
 * 注意:
 * - 署名検証は行わない（ここは “sub を取り出して URL 生成などに使う” ための補助）。
 * - 認証の正当性はサーバ側（WS handshake / Supabase）で担保する。
 */

/**
 * JWT から user id（sub）を抽出する。
 *
 * @param token - JWT 文字列（Bearer ではなく token 本体想定）
 * @returns user id（sub）または null
 */
export function extractUserIdFromJwt(token: unknown): string | null {
  try {
    const parts = String(token || '').split('.');
    if (parts.length !== 3) return null;
    // base64url -> base64
    let payloadB64 = parts[1].replace(/-/g, '+').replace(/_/g, '/');
    const pad = (4 - (payloadB64.length % 4)) % 4;
    if (pad) payloadB64 += '='.repeat(pad);
    const payloadJson = Buffer.from(payloadB64, 'base64').toString('utf8');
    const payload = JSON.parse(payloadJson) as {
      sub?: unknown;
      user_id?: unknown;
      user?: { id?: unknown };
    };
    const sub = payload?.sub || payload?.user_id || payload?.user?.id;
    return typeof sub === 'string' && sub ? sub : null;
  } catch {
    return null;
  }
}
