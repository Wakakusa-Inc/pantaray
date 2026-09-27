import { User, Session, AuthError } from '@supabase/supabase-js';
import type { SignUpResult } from '../lib/signUpResult';

export type AuthContextType = {
  user: User | null;
  session: Session | null;
  loading: boolean;
  signIn: (email: string, password: string) => Promise<{ error: AuthError | null }>;
  signUp: (email: string, password: string) => Promise<SignUpResult>;
  signOut: () => Promise<{ error: AuthError | null }>;
};
