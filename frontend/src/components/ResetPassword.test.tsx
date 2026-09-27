import React from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import {
  hasVerifiedPasswordRecoverySession,
  markPasswordRecoveryRedirectPending,
  markPasswordRecoverySessionVerified,
} from '@/lib/passwordRecoverySession';

const { navigateMock } = vi.hoisted(() => ({
  navigateMock: vi.fn(),
}));

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom');
  return {
    ...actual,
    useNavigate: () => navigateMock,
  };
});

vi.mock('@/components/BrandWordmark', () => {
  return { BrandWordmark: () => React.createElement('div', { 'data-testid': 'brand' }) };
});

const translate = (key: string) => key;

vi.mock('@/context/useI18n', () => {
  return {
    useI18n: () => ({
      t: translate,
    }),
  };
});

const getSessionMock = vi.fn();
const exchangeCodeForSessionMock = vi.fn();
const updateUserMock = vi.fn();
const signOutMock = vi.fn();
const unsubscribeMock = vi.fn();
const mockSupabaseAuthStorageKey = 'sb-test-auth-token';
type AuthStateCallback = (event: string, session: { user: { id: string } } | null) => void;
const authStateCallbacks: AuthStateCallback[] = [];
const successfulCodeExchange = {
  data: {
    session: {
      access_token: 'access-token',
      refresh_token: 'refresh-token',
      user: { id: 'user-1' },
    },
    user: { id: 'user-1' },
  },
  error: null,
};

vi.mock('../lib/supabase', () => {
  return {
    supabaseAuthStorageKey: 'sb-test-auth-token',
    supabase: {
      auth: {
        getSession: (...args: unknown[]) => getSessionMock(...args),
        exchangeCodeForSession: (...args: unknown[]) => exchangeCodeForSessionMock(...args),
        updateUser: (...args: unknown[]) => updateUserMock(...args),
        signOut: (...args: unknown[]) => signOutMock(...args),
        onAuthStateChange: (callback: AuthStateCallback) => {
          authStateCallbacks.push(callback);
          return {
            data: {
              subscription: {
                unsubscribe: unsubscribeMock,
              },
            },
          };
        },
      },
    },
  };
});

import ResetPassword from './ResetPassword';

describe('ResetPassword', () => {
  afterEach(() => {
    cleanup();
  });

  beforeEach(() => {
    window.history.pushState({}, '', '/');
    window.sessionStorage.clear();
    window.localStorage.clear();
    authStateCallbacks.length = 0;
    vi.clearAllMocks();
    getSessionMock.mockResolvedValue({
      data: {
        session: {
          access_token: 'access-token',
          refresh_token: 'refresh-token',
          user: { id: 'user-1' },
        },
      },
      error: null,
    });
    exchangeCodeForSessionMock.mockResolvedValue(successfulCodeExchange);
    updateUserMock.mockResolvedValue({ error: null });
    signOutMock.mockImplementation(async () => {
      getSessionMock.mockResolvedValueOnce({
        data: { session: null },
        error: null,
      });
      return { error: null };
    });
    navigateMock.mockClear();
  });

  it('updates the password from the recovery session after Supabase clears URL tokens', async () => {
    markPasswordRecoverySessionVerified(window.sessionStorage);

    render(
      <MemoryRouter initialEntries={['/reset-password']}>
        <ResetPassword />
      </MemoryRouter>
    );

    const submitButton = await screen.findByRole('button', {
      name: 'auth.form.updatePasswordButton',
    });

    await waitFor(() => expect((submitButton as HTMLButtonElement).disabled).toBe(false));

    fireEvent.change(screen.getByPlaceholderText('auth.form.passwordNewPlaceholder'), {
      target: { value: 'Password1!' },
    });
    fireEvent.change(screen.getByPlaceholderText('auth.form.passwordConfirmPlaceholder'), {
      target: { value: 'Password1!' },
    });
    fireEvent.click(submitButton);

    await screen.findByText('auth.message.passwordUpdated');

    expect(updateUserMock).toHaveBeenCalledWith({ password: 'Password1!' });
    expect(signOutMock).toHaveBeenCalledWith({ scope: 'local' });
  });

  it('does not complete password reset when the recovery session remains signed in', async () => {
    markPasswordRecoverySessionVerified(window.sessionStorage);
    signOutMock.mockResolvedValue({ error: null });

    render(
      <MemoryRouter initialEntries={['/reset-password']}>
        <ResetPassword />
      </MemoryRouter>
    );

    const submitButton = await screen.findByRole('button', {
      name: 'auth.form.updatePasswordButton',
    });

    await waitFor(() => expect((submitButton as HTMLButtonElement).disabled).toBe(false));

    fireEvent.change(screen.getByPlaceholderText('auth.form.passwordNewPlaceholder'), {
      target: { value: 'Password1!' },
    });
    fireEvent.change(screen.getByPlaceholderText('auth.form.passwordConfirmPlaceholder'), {
      target: { value: 'Password1!' },
    });
    fireEvent.click(submitButton);

    await screen.findByText('auth.error.generic');

    expect(updateUserMock).toHaveBeenCalledWith({ password: 'Password1!' });
    expect(signOutMock).toHaveBeenCalledWith({ scope: 'local' });
    expect(navigateMock).not.toHaveBeenCalled();
  });

  it('clears a stale recovery marker when there is no Supabase session', async () => {
    markPasswordRecoverySessionVerified(window.sessionStorage);
    getSessionMock.mockResolvedValueOnce({
      data: { session: null },
      error: null,
    });

    render(
      <MemoryRouter initialEntries={['/reset-password']}>
        <ResetPassword />
      </MemoryRouter>
    );

    await screen.findByText('auth.error.resetLinkInvalid');

    expect(hasVerifiedPasswordRecoverySession(window.sessionStorage)).toBe(false);
    expect(updateUserMock).not.toHaveBeenCalled();
  });

  it('enables password reset after a pending redirect is verified by Supabase recovery event', async () => {
    markPasswordRecoveryRedirectPending(window.sessionStorage, 'implicit');

    render(
      <MemoryRouter initialEntries={['/reset-password']}>
        <ResetPassword />
      </MemoryRouter>
    );

    const submitButton = await screen.findByRole('button', {
      name: 'auth.form.updatePasswordButton',
    });

    await waitFor(() => expect(authStateCallbacks.length).toBeGreaterThan(0));
    authStateCallbacks.forEach((callback) =>
      callback('PASSWORD_RECOVERY', { user: { id: 'user-1' } })
    );

    await waitFor(() => expect((submitButton as HTMLButtonElement).disabled).toBe(false));
    expect(hasVerifiedPasswordRecoverySession(window.sessionStorage)).toBe(true);
  });

  it('enables password reset after a pending PKCE redirect is verified by code exchange', async () => {
    window.history.pushState({}, '', '/reset-password?code=RECOVERY_CODE');
    markPasswordRecoveryRedirectPending(window.sessionStorage, 'code');
    window.localStorage.setItem(
      `${mockSupabaseAuthStorageKey}-code-verifier`,
      'verifier/PASSWORD_RECOVERY'
    );

    render(
      <MemoryRouter initialEntries={['/reset-password']}>
        <ResetPassword />
      </MemoryRouter>
    );

    const submitButton = await screen.findByRole('button', {
      name: 'auth.form.updatePasswordButton',
    });

    await waitFor(() => expect((submitButton as HTMLButtonElement).disabled).toBe(false));
    expect(exchangeCodeForSessionMock).toHaveBeenCalledWith('RECOVERY_CODE');
    expect(hasVerifiedPasswordRecoverySession(window.sessionStorage)).toBe(true);
  });

  it('deduplicates PKCE code exchange across StrictMode effect replay', async () => {
    window.history.pushState({}, '', '/reset-password?code=STRICT_MODE_CODE');
    markPasswordRecoveryRedirectPending(window.sessionStorage, 'code');
    window.localStorage.setItem(
      `${mockSupabaseAuthStorageKey}-code-verifier`,
      'verifier/PASSWORD_RECOVERY'
    );

    let resolveExchange: (value: typeof successfulCodeExchange) => void = () => {};
    exchangeCodeForSessionMock.mockReturnValueOnce(
      new Promise((resolve) => {
        resolveExchange = resolve;
      })
    );

    render(
      <React.StrictMode>
        <MemoryRouter initialEntries={['/reset-password']}>
          <ResetPassword />
        </MemoryRouter>
      </React.StrictMode>
    );

    await waitFor(() => expect(exchangeCodeForSessionMock).toHaveBeenCalledTimes(1));

    await act(async () => {
      resolveExchange(successfulCodeExchange);
    });

    const submitButton = await screen.findByRole('button', {
      name: 'auth.form.updatePasswordButton',
    });

    await waitFor(() => expect((submitButton as HTMLButtonElement).disabled).toBe(false));
    expect(exchangeCodeForSessionMock).toHaveBeenCalledWith('STRICT_MODE_CODE');
    expect(exchangeCodeForSessionMock).toHaveBeenCalledTimes(1);
    expect(hasVerifiedPasswordRecoverySession(window.sessionStorage)).toBe(true);
  });

  it('rejects a PKCE exchange that is not tied to password recovery', async () => {
    window.history.pushState({}, '', '/reset-password?code=NORMAL_CODE');
    markPasswordRecoveryRedirectPending(window.sessionStorage, 'code');
    window.localStorage.setItem(`${mockSupabaseAuthStorageKey}-code-verifier`, 'verifier');

    render(
      <MemoryRouter initialEntries={['/reset-password']}>
        <ResetPassword />
      </MemoryRouter>
    );

    await screen.findByText('auth.error.resetLinkInvalid');

    expect(exchangeCodeForSessionMock).not.toHaveBeenCalled();
    expect(hasVerifiedPasswordRecoverySession(window.sessionStorage)).toBe(false);
    expect(updateUserMock).not.toHaveBeenCalled();
  });
});
