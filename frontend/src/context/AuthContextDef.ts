import { createContext } from 'react';
import { User, Session, AuthError } from '@supabase/supabase-js';
import type { AuthStatus } from '../../electron/src/ipc/context';
import type { LocalRuntimeState } from '../../electron/src/auth/localRuntimeState';
import type { SignUpResult } from '../lib/signUpResult';

// 認証コンテキストの型定義
export type AuthContextType = {
  authStatus: AuthStatus;
  user: User | null;
  session: Session | null;
  loading: boolean;
  runtimeState: LocalRuntimeState;
  signIn: (email: string, password: string) => Promise<{ error: AuthError | null }>;
  signUp: (email: string, password: string) => Promise<SignUpResult>;
  signOut: () => Promise<{ error: AuthError | null }>;
  resetPassword: (email: string) => Promise<{ error: AuthError | null }>;
};

// AuthContext の定義
export const AuthContext = createContext<AuthContextType | undefined>(undefined);
