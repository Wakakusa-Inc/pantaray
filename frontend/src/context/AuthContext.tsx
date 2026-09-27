import React, { useState, useEffect, ReactNode } from 'react';
import { AuthContext } from './AuthContextDef';
import { User, Session, AuthError } from '@supabase/supabase-js';
import { supabase, getRedirectUrl, getPasswordResetRedirectUrl } from '../lib/supabase';
import { INITIAL_LOCAL_RUNTIME_STATE } from '../../electron/src/auth/localRuntimeState';
import { resolveSupabaseSignUpResult } from '../lib/signUpResult';
import type { SignUpResult } from '../lib/signUpResult';
import { PANTARAY_ACCOUNT_LOGIN_ENABLED } from '../../electron/src/auth/accountLoginFeature';

type ElectronAuthState = Awaited<
  ReturnType<NonNullable<NonNullable<Window['electron']>['auth']>['getState']>
>;

const ELECTRON_USER_AUDIENCE = 'authenticated';
const EMPTY_USER_METADATA = {};
const EMPTY_APP_METADATA = {};

function toElectronUser(stateUser: ElectronAuthState['user']): User | null {
  if (stateUser === null) {
    return null;
  }

  return {
    id: stateUser.id,
    email: stateUser.email ?? undefined,
    aud: ELECTRON_USER_AUDIENCE,
    app_metadata: EMPTY_APP_METADATA,
    user_metadata: EMPTY_USER_METADATA,
    created_at: new Date().toISOString(),
  };
}

function toAuthError(error: unknown): AuthError {
  if (error instanceof AuthError) {
    return error;
  }
  return new AuthError(error instanceof Error ? error.message : String(error));
}

export const AuthProvider: React.FC<{ children: ReactNode }> = ({ children }) => {
  const accountAuthAvailable = PANTARAY_ACCOUNT_LOGIN_ENABLED || Boolean(window.electron?.auth);
  const [authStatus, setAuthStatus] = useState<ElectronAuthState['authStatus']>(
    accountAuthAvailable ? 'initializing' : 'unauthenticated'
  );
  const [user, setUser] = useState<User | null>(null);
  const [session, setSession] = useState<Session | null>(null);
  const [loading, setLoading] = useState(accountAuthAvailable);
  const [runtimeState, setRuntimeState] = useState(INITIAL_LOCAL_RUNTIME_STATE);

  useEffect(() => {
    if (!accountAuthAvailable) return;
    const electronAuth = window.electron?.auth;
    let active = true;
    let receivedNotification = false;
    const handleInitialError = () => {
      if (!active || receivedNotification) return;
      console.error('セッション初期化に失敗しました');
      setLoading(false);
    };
    let unsubscribe: (() => void) | undefined;

    if (electronAuth) {
      const applyState = (next: ElectronAuthState) => {
        setAuthStatus(next.authStatus);
        setSession(null);
        setUser(toElectronUser(next.user));
        setRuntimeState(next.runtimeState);
        setLoading(next.authStatus === 'initializing');
      };
      unsubscribe = electronAuth.onStateChanged?.((next) => {
        if (!active) return;
        receivedNotification = true;
        applyState(next);
      });
      // A notification is newer than the startup snapshot, even if the read finishes later.
      void electronAuth.getState().then((next) => {
        if (active && !receivedNotification) applyState(next);
      }, handleInitialError);
    } else {
      const applySession = (next: Session | null) => {
        setAuthStatus(next ? 'authenticated' : 'unauthenticated');
        setSession(next);
        setUser(next?.user ?? null);
        setRuntimeState(INITIAL_LOCAL_RUNTIME_STATE);
        setLoading(false);
      };
      const {
        data: { subscription },
      } = supabase.auth.onAuthStateChange((_event, next) => {
        if (!active) return;
        receivedNotification = true;
        applySession(next);
      });
      unsubscribe = () => subscription.unsubscribe();
      void supabase.auth.getSession().then(({ data, error }) => {
        if (!active || receivedNotification) return;
        if (error) handleInitialError();
        else applySession(data.session);
      }, handleInitialError);
    }

    return () => {
      active = false;
      unsubscribe?.();
    };
  }, [accountAuthAvailable]);

  const signIn = async (email: string, password: string) => {
    if (!PANTARAY_ACCOUNT_LOGIN_ENABLED) {
      return { error: new AuthError('Pantaray account login is disabled.') };
    }
    try {
      // Electron は外部ブラウザでログインするため、renderer からの signIn はサポートしない
      if (typeof window !== 'undefined' && window.electron?.ipcRenderer) {
        return { error: new AuthError('Electron では外部ブラウザでログインしてください') };
      }
      const { error } = await supabase.auth.signInWithPassword({
        email,
        password,
      });
      return { error };
    } catch (error) {
      console.error('サインインエラー:', error);
      return { error: toAuthError(error) };
    }
  };

  const signUp = async (email: string, password: string): Promise<SignUpResult> => {
    if (!PANTARAY_ACCOUNT_LOGIN_ENABLED) {
      return { status: 'failed', error: new AuthError('Pantaray account login is disabled.') };
    }
    try {
      // Electron は外部ブラウザでサインアップするため、renderer からの signUp はサポートしない
      if (typeof window !== 'undefined' && window.electron?.ipcRenderer) {
        return {
          status: 'failed',
          error: new AuthError('Electron では外部ブラウザでサインアップしてください'),
        } as const;
      }
      const { data, error } = await supabase.auth.signUp({
        email,
        password,
        options: {
          emailRedirectTo: getRedirectUrl(),
        },
      });
      return resolveSupabaseSignUpResult(data, error);
    } catch (error) {
      console.error('サインアップエラー:', error);
      return { status: 'failed', error: toAuthError(error) };
    }
  };

  const signOut = async () => {
    try {
      if (typeof window !== 'undefined' && window.electron?.auth?.signOut) {
        const res = await window.electron.auth.signOut();
        if (!res || res.ok !== true) {
          return { error: new AuthError(res?.error || 'Sign out failed') };
        }
        return { error: null };
      }

      // Web: セッションを強制的にリフレッシュしてからサインアウト
      await supabase.auth.refreshSession();
      const { error } = await supabase.auth.signOut();
      return { error };
    } catch (error) {
      console.error('サインアウトエラー:', error);
      return { error: toAuthError(error) };
    }
  };

  const resetPassword = async (email: string) => {
    if (!PANTARAY_ACCOUNT_LOGIN_ENABLED) {
      return { error: new AuthError('Pantaray account login is disabled.') };
    }
    try {
      // Electron は外部ブラウザでリセットを行うため、renderer からの resetPassword はサポートしない
      if (typeof window !== 'undefined' && window.electron?.ipcRenderer) {
        return {
          error: new AuthError('Electron では外部ブラウザでパスワードリセットしてください'),
        };
      }
      const { error } = await supabase.auth.resetPasswordForEmail(email, {
        redirectTo: getPasswordResetRedirectUrl(),
      });
      return { error };
    } catch (error) {
      console.error('パスワードリセットエラー:', error);
      return { error: toAuthError(error) };
    }
  };

  return (
    <AuthContext.Provider
      value={{
        authStatus,
        user,
        session,
        loading,
        runtimeState,
        signIn,
        signUp,
        signOut,
        resetPassword,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
};
