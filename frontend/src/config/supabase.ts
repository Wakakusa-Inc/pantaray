/// <reference types="vite/client" />
import { createClient } from '@supabase/supabase-js';
import { PANTARAY_ACCOUNT_LOGIN_ENABLED } from '../../electron/src/auth/accountLoginFeature';
import {
  getPasswordRecoveryRedirectKind,
  getBrowserSessionStorage,
  markPasswordRecoveryRedirectPending,
  markPasswordRecoverySessionVerified,
} from '../lib/passwordRecoverySession';

const supabaseUrl = import.meta.env.VITE_SUPABASE_URL;
// Supabase publishable key（sb_publishable_...）を使用する。
// - 公開前提キー（クライアントに埋め込む前提）
// - Auth/DB/Storage へのアクセスは RLS で制御される
const supabaseKey = import.meta.env.VITE_SUPABASE_PUBLISHABLE_KEY;
const isDev = import.meta.env.DEV;
const hasWindow = typeof window !== 'undefined';
const isElectron = hasWindow && Boolean(window.electron?.ipcRenderer);
const initialPasswordRecoveryRedirectKind =
  hasWindow && !isElectron ? getPasswordRecoveryRedirectKind(window.location.href) : null;

function resolveSupabaseAuthStorageKey(urlString: string): string {
  const url = new URL(urlString);
  return `sb-${url.hostname.split('.')[0]}-auth-token`;
}

function cleanupLegacySupabaseLocalStorage(): void {
  if (typeof window === 'undefined') return;
  // Electron でのみ実行（Web の auth 永続は従来どおり localStorage を利用する）
  if (!isElectron) return;
  try {
    const ls = window.localStorage;
    const keys: string[] = [];
    for (let i = 0; i < ls.length; i += 1) {
      const k = ls.key(i);
      if (!k) continue;
      // supabase-js の既定キー（例: sb-<projectRef>-auth-token）
      if (/^sb-.*-auth-token$/.test(k)) keys.push(k);
    }
    for (const k of keys) {
      try {
        ls.removeItem(k);
      } catch {
        // no-op
      }
    }
  } catch {
    // no-op
  }
}

function createInMemoryStorage(): Storage {
  const mem = new Map<string, string>();
  // supabase-js が最低限利用する API を実装する（Storage 準拠に寄せる）
  return {
    get length() {
      return mem.size;
    },
    clear() {
      mem.clear();
    },
    getItem(key: string) {
      return mem.has(key) ? mem.get(key)! : null;
    },
    key(index: number) {
      const keys = Array.from(mem.keys());
      return keys[index] ?? null;
    },
    removeItem(key: string) {
      mem.delete(key);
    },
    setItem(key: string, value: string) {
      mem.set(key, value);
    },
  };
}

function getWebStorage(): Storage | undefined {
  if (typeof window === 'undefined') return undefined;
  try {
    return window.localStorage;
  } catch {
    return undefined;
  }
}

// 環境変数の検証
function validateConfig() {
  const issues: string[] = [];

  if (!supabaseUrl) {
    issues.push('VITE_SUPABASE_URL が設定されていません');
  } else {
    try {
      const url = new URL(supabaseUrl);
      // 開発では http を許容（Cloud Run/本番では https 推奨）
      if (!isDev && !url.protocol.startsWith('https')) {
        issues.push('VITE_SUPABASE_URL は https である必要があります');
      }
    } catch (_error) {
      issues.push('VITE_SUPABASE_URL が不正なURLフォーマットです');
    }
  }

  if (!supabaseKey) {
    issues.push('VITE_SUPABASE_PUBLISHABLE_KEY が設定されていません');
  } else {
    // publishable key のフォーマットを軽くチェック（完全検証はしない）
    // 例: sb_publishable_...
    if (!/^sb_publishable_/i.test(supabaseKey)) {
      issues.push(
        'VITE_SUPABASE_PUBLISHABLE_KEY が不正なフォーマットです（sb_publishable_... 形式が必要）'
      );
    }
  }

  if (issues.length > 0) {
    throw new Error(`Supabase設定エラー:\n${issues.join('\n')}`);
  }
}

// 開発環境でも設定を検証
validateConfig();

export const supabaseAuthStorageKey = resolveSupabaseAuthStorageKey(supabaseUrl);

// Electron: 旧バージョンで localStorage に保存されていた Supabase セッションを除去する
cleanupLegacySupabaseLocalStorage();

// Supabaseクライアントの設定
const supabaseOptions = {
  auth: {
    autoRefreshToken: !isElectron && PANTARAY_ACCOUNT_LOGIN_ENABLED,
    // Electron: セッション永続は main が行う（renderer は localStorage に保存しない）
    persistSession: !isElectron && PANTARAY_ACCOUNT_LOGIN_ENABLED,
    // Electron: deep link は main が処理するため、URL からの検出も不要
    detectSessionInUrl:
      !isElectron &&
      PANTARAY_ACCOUNT_LOGIN_ENABLED &&
      initialPasswordRecoveryRedirectKind !== 'code',
    storageKey: supabaseAuthStorageKey,
    storage:
      isElectron || !PANTARAY_ACCOUNT_LOGIN_ENABLED ? createInMemoryStorage() : getWebStorage(),
  },
  global: {
    headers: { 'x-application-name': 'pantaray-frontend' },
  },
};

export const supabase = createClient(supabaseUrl, supabaseKey, supabaseOptions);

if (!isElectron) {
  if (initialPasswordRecoveryRedirectKind) {
    markPasswordRecoveryRedirectPending(
      getBrowserSessionStorage(),
      initialPasswordRecoveryRedirectKind
    );
  }

  supabase.auth.onAuthStateChange((event) => {
    const storage = getBrowserSessionStorage();
    if (event === 'PASSWORD_RECOVERY') {
      markPasswordRecoverySessionVerified(storage);
      return;
    }
  });
}

// 開発環境では認証状態の変更をログ出力
if (isDev && !isElectron) {
  supabase.auth.onAuthStateChange((event, session) => {
    // センシティブ情報（token等）を避けて最小限の情報のみ出す
    console.log('Auth state changed:', { event, userId: session?.user?.id || null });
  });
}
