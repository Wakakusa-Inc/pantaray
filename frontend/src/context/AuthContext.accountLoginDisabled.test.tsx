import { act, cleanup, renderHook } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';

import { useAuth } from '../hooks/useAuth';
import { AuthProvider } from './AuthContext';

const webAuth = vi.hoisted(() => ({
  getSession: vi.fn(),
  onAuthStateChange: vi.fn(),
  signInWithPassword: vi.fn(),
  signUp: vi.fn(),
  resetPasswordForEmail: vi.fn(),
}));
vi.mock('../lib/supabase', () => ({ getSupabase: () => ({ auth: webAuth }) }));

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

it('does not restore a web account session or send account auth requests when login is disabled', async () => {
  const { result } = renderHook(useAuth, { wrapper: AuthProvider });
  expect(result.current.authStatus).toBe('unauthenticated');
  expect(result.current.loading).toBe(false);
  expect(webAuth.getSession).not.toHaveBeenCalled();
  expect(webAuth.onAuthStateChange).not.toHaveBeenCalled();

  await act(async () => {
    expect((await result.current.signIn('user@example.com', 'password')).error).not.toBeNull();
    expect((await result.current.signUp('user@example.com', 'password')).status).toBe('failed');
    expect((await result.current.resetPassword('user@example.com')).error).not.toBeNull();
  });
  expect(webAuth.signInWithPassword).not.toHaveBeenCalled();
  expect(webAuth.signUp).not.toHaveBeenCalled();
  expect(webAuth.resetPasswordForEmail).not.toHaveBeenCalled();
});
