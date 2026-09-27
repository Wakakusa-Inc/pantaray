import type { AuthState } from '../ipc/context';

export type RuntimeConfigLike = {
  supabase_url?: string;
  supabase_publishable_key?: string;
  web_app_origin?: string;
  backend_url?: string;
};

export type SessionTokenPair = {
  access_token: string;
  refresh_token: string;
  desktop_session_version: string;
};

export type SessionApplyResult = {
  ok: boolean;
  error?: unknown;
};

export type SupabaseSessionState = {
  authStatus?: AuthState['authStatus'];
  isLoggedIn: boolean;
  user: AuthState['user'];
};

export type SupabaseSessionInitializationStatus = 'initializing' | 'ready' | 'failed';

export type ExpiredCloudIdentity = {
  userId: string;
  sessionVersion: string;
};

export type SupabaseSessionManagerLike = {
  initialize?: () => Promise<void>;
  getState?: () => SupabaseSessionState;
  getAccessToken?: () => string | null;
  getDesktopSessionVersion?: () => string | null;
  /** 更新できなくなったセッションのアカウント。`authStatus: 'expired'` のときだけ非 null。 */
  getExpiredCloudIdentity?: () => ExpiredCloudIdentity | null;
  signOut?: (options?: { reason?: 'user' | 'unauthorized' }) => Promise<void>;
  onStateChanged?: (handler: (state: SupabaseSessionState) => void) => unknown;
  applySessionTokens?: (tokens: SessionTokenPair) => Promise<SessionApplyResult>;
};
