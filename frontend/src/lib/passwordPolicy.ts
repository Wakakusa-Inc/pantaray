/**
 * パスワードポリシー（フロントエンド側）
 *
 * 目的:
 * - Signup / Reset Password で要件がズレないように SSOT として集約する
 *
 * 注意:
 * - これは UI/UX のための検証です。最終的な強制は Supabase Auth 側の設定に依存します。
 */

export type PasswordPolicyResult =
  | { ok: true }
  | { ok: false; reason: 'empty' | 'spaces' | 'requirements'; missing: string[] };

/**
 * パスワードがポリシーを満たすか検証する。
 *
 * 要件:
 * - 8文字以上
 * - 大文字（A–Z）を1文字以上含む
 * - 小文字（a–z）を1文字以上含む
 * - 数字（0–9）を1文字以上含む
 * - 記号を1文字以上含む（空白は不可）
 *
 * 表示（UI）について:
 * - 詳細は missing に列挙し、画面側で「1行」に圧縮して表示する
 */
export function validatePassword(password: string): PasswordPolicyResult {
  const trimmed = password ?? '';

  if (!trimmed) {
    return { ok: false, reason: 'empty', missing: ['password'] };
  }

  // 空白は不可（コピー&ペースト時の事故を防ぐ）
  if (/\s/.test(trimmed)) {
    return {
      ok: false,
      reason: 'spaces',
      missing: ['no_spaces'],
    };
  }

  const missing: string[] = [];

  if (trimmed.length < 8) missing.push('min_length');
  if (!/[A-Z]/.test(trimmed)) missing.push('uppercase');
  if (!/[a-z]/.test(trimmed)) missing.push('lowercase');
  if (!/\d/.test(trimmed)) missing.push('number');
  if (!/[^A-Za-z0-9]/.test(trimmed)) missing.push('special');

  if (missing.length > 0) {
    return { ok: false, reason: 'requirements', missing };
  }

  return { ok: true };
}
