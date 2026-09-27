import { AuthError } from '@supabase/supabase-js';
import { describe, expect, it } from 'vitest';

import { resolveSupabaseSignUpResult } from './signUpResult';

describe('resolveSupabaseSignUpResult', () => {
  it('treats a Supabase obfuscated existing user as already registered', () => {
    const result = resolveSupabaseSignUpResult({ user: { identities: [] } }, null);

    expect(result.status).toBe('already_registered');
    expect(result.error).toBeInstanceOf(AuthError);
  });

  it('treats Supabase duplicate-account errors as already registered', () => {
    const result = resolveSupabaseSignUpResult(
      { user: null },
      new AuthError('User already registered')
    );

    expect(result.status).toBe('already_registered');
  });

  it('treats a user with an identity as created', () => {
    const result = resolveSupabaseSignUpResult(
      { user: { identities: [{ id: 'identity-1' }] } },
      null
    );

    expect(result).toEqual({ status: 'created', error: null });
  });
});
