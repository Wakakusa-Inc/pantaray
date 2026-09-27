// 単一のSupabaseクライアントを再利用
import { supabase, supabaseAuthStorageKey } from '../config/supabase';
import { getWebAppOrigin } from '../config/webAppUrl';
export { supabase, supabaseAuthStorageKey };

/**
 * Supabase Auth の確認メールから遷移させるURLを返す。
 *
 * 背景:
 * - `emailRedirectTo` が `window.location.origin` に依存すると、開発中の `localhost` から登録した場合に
 *   確認メールのリンクも `localhost` になり、本番Webへ遷移できない。
 *
 * 方針:
 * - Web版の起点URLは `VITE_WEB_APP_URL` をSSOTとし、フォールバックは持たない。
 * - 未設定の場合は明示的に例外で失敗させ、環境差分による静かな誤動作を防ぐ。
 */
export const getRedirectUrl = () => {
  const appUrl = getWebAppOrigin();
  // 確認メールのリダイレクト先を設定
  // WebはクリーンURL化したため、`/confirmation-success` を指定する
  return `${appUrl}/confirmation-success`;
};

/**
 * Supabase Auth のパスワードリセットメールから遷移させるURLを返す。
 *
 * `VITE_WEB_APP_URL` 未設定時は例外で失敗させる（フォールバックしない）。
 */
export const getPasswordResetRedirectUrl = () => {
  const appUrl = getWebAppOrigin();
  // WebはクリーンURL化したため、`/reset-password` を指定する
  return `${appUrl}/reset-password`;
};

// Supabaseの接続確認
export const checkSupabaseConnection = async () => {
  try {
    // NOTE:
    // - DB直アクセス（PostgREST）を原則禁止するため、存在するか不明な公開テーブルを叩かない。
    // - Auth のみで疎通確認する（未ログイン時でも API 自体が到達可能なら OK を返せる）。
    const { error } = await supabase.auth.getUser();
    return !error;
  } catch (error) {
    console.error('Supabase connection check failed:', error);
    return false;
  }
};

// セッション情報を取得
export const getSession = async () => {
  try {
    const {
      data: { user },
      error,
    } = await supabase.auth.getUser();
    if (error) throw error;
    return { user, error: null };
  } catch (error) {
    console.error('Error getting session:', error);
    return { user: null, error };
  }
};

// ログアウト
export const signOut = async () => {
  try {
    const { error } = await supabase.auth.signOut();
    if (error) throw error;
    return { error: null };
  } catch (error) {
    console.error('Error signing out:', error);
    return { error };
  }
};
