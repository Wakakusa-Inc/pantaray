import { AuthError } from '@supabase/supabase-js';

export type SignUpStatus = 'created' | 'already_registered' | 'failed';

export type SignUpResult =
  | { status: 'created'; error: null }
  | { status: 'already_registered'; error: AuthError }
  | { status: 'failed'; error: AuthError };

export type SupabaseSignUpData = {
  user: { identities?: readonly object[] | null } | null;
};

const ALREADY_REGISTERED_ERROR_MESSAGE = 'Account already exists.';

function createAlreadyRegisteredError(): AuthError {
  return new AuthError(ALREADY_REGISTERED_ERROR_MESSAGE);
}

function isAlreadyRegisteredError(error: AuthError): boolean {
  const message = error.message.toLowerCase();
  return message.includes('already registered') || message.includes('already exists');
}

function isObfuscatedExistingUser(user: SupabaseSignUpData['user']): boolean {
  return Array.isArray(user?.identities) && user.identities.length === 0;
}

export function resolveSupabaseSignUpResult(
  data: SupabaseSignUpData,
  error: AuthError | null
): SignUpResult {
  if (error) {
    return {
      status: isAlreadyRegisteredError(error) ? 'already_registered' : 'failed',
      error,
    };
  }

  if (isObfuscatedExistingUser(data.user)) {
    return {
      status: 'already_registered',
      error: createAlreadyRegisteredError(),
    };
  }

  return { status: 'created', error: null };
}
