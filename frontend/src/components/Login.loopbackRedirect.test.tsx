import React from 'react';
import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import { fireEvent, render, screen } from '@testing-library/react';

// NOTE: Login.tsx imports these modules via relative/alias paths. Mock them here to isolate behavior.
vi.mock('../hooks/useAuth', () => {
  return {
    useAuth: () => ({
      signIn: vi.fn(async () => ({ error: null })),
    }),
  };
});

vi.mock('@/components/BrandWordmark', () => {
  return { BrandWordmark: () => React.createElement('div', { 'data-testid': 'brand' }) };
});

vi.mock('@/context/useI18n', () => {
  return {
    useI18n: () => ({
      // 差し込み値も画面に出るようにして、表示されるアカウントを検証できるようにする。
      t: (k: unknown, vars?: Record<string, string | number>) =>
        vars ? `${String(k)} ${Object.values(vars).join(' ')}` : String(k),
    }),
  };
});

const getSessionMock = vi.fn(async (..._args: unknown[]) => ({
  data: {
    session: {
      access_token: 'AT',
      refresh_token: 'RT',
      user: { email: 'alice@example.test' },
    },
  },
}));

vi.mock('../lib/supabase', () => {
  return {
    getSupabase: () => ({
      auth: {
        getSession: (...args: unknown[]) => getSessionMock(...args),
        signOut: vi.fn(async () => ({ error: null })),
      },
    }),
  };
});

import Login from './Login';

const DESKTOP_RETURN_ENTRY =
  '/login?desktop=1&attempt_id=A1&code_challenge=C1&loopback_redirect_url=' +
  encodeURIComponent('http://127.0.0.1:43121/auth/callback?state=S1');

describe('Login (desktop return)', () => {
  const originalFetch = globalThis.fetch;
  const originalElectron = window.electron;
  let assignSpy: ReturnType<typeof vi.spyOn> | null = null;
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    getSessionMock.mockClear();
    vi.stubEnv('VITE_WEB_APP_URL', 'https://app.example.test');
    const fetchImpl: typeof fetch = async () =>
      new Response(JSON.stringify({ ok: true, exchange_code: 'EX' }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      });
    fetchMock = vi.fn(fetchImpl);
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    // happy-dom allows spying on location.assign
    assignSpy = vi.spyOn(window.location, 'assign').mockImplementation(() => {});
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
    window.electron = originalElectron;
    assignSpy?.mockRestore();
    assignSpy = null;
    vi.unstubAllEnvs();
  });

  it('prefers the desktop loopback over the deep link after form login', async () => {
    render(
      <MemoryRouter initialEntries={[DESKTOP_RETURN_ENTRY]}>
        <Login />
      </MemoryRouter>
    );

    fireEvent.change(screen.getByPlaceholderText('auth.form.emailPlaceholder'), {
      target: { value: 'a@b.com' },
    });
    fireEvent.change(screen.getByPlaceholderText('auth.form.passwordPlaceholder'), {
      target: { value: 'pw' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'auth.form.loginButton' }));

    // wait until redirect attempted
    await screen.findByText('auth.message.loginSuccessOpening');

    expect(assignSpy).not.toBeNull();
    const loopbackCall = assignSpy!.mock.calls.find(([value]: [unknown]) =>
      String(value || '').includes('http://127.0.0.1:')
    );
    expect(loopbackCall).toBeDefined();
    const calledWith = String(loopbackCall?.[0] || '');
    expect(calledWith).toContain('http://127.0.0.1:32100/auth/callback');
    expect(calledWith).not.toContain('43121');
    expect(calledWith).toContain('state=S1');
    expect(calledWith).toContain('attempt_id=A1');
    expect(calledWith).toContain('exchange_code=EX');
    expect(calledWith.startsWith('pantaray://')).toBe(false);
  });

  it('does not hand a browser session over before the user confirms', async () => {
    render(
      <MemoryRouter initialEntries={[DESKTOP_RETURN_ENTRY]}>
        <Login />
      </MemoryRouter>
    );

    await screen.findByRole('button', { name: 'auth.desktopHandoff.continue' });
    expect(screen.getByText(/alice@example\.test/)).toBeVisible();
    expect(screen.getByText('auth.desktopHandoff.hint')).toBeVisible();
    expect(fetchMock).not.toHaveBeenCalled();
    expect(assignSpy!.mock.calls).toHaveLength(0);
  });

  it('hands the browser session over once the user confirms', async () => {
    render(
      <MemoryRouter initialEntries={[DESKTOP_RETURN_ENTRY]}>
        <Login />
      </MemoryRouter>
    );

    fireEvent.click(await screen.findByRole('button', { name: 'auth.desktopHandoff.continue' }));

    await screen.findByText('auth.message.loginSuccessOpening');
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(String(fetchMock.mock.calls[0][0])).toContain('/desktop_auth/issue');
    const calledWith = String(assignSpy!.mock.calls[0]?.[0] || '');
    expect(calledWith).toContain('http://127.0.0.1:32100/auth/callback');
    expect(calledWith).toContain('exchange_code=EX');
  });

  it('opens password reset without starting a desktop loopback attempt', async () => {
    const startBrowserLogin = vi.fn();
    const send = vi.fn();
    window.electron = {
      auth: {
        startBrowserLogin,
      },
      ipcRenderer: {
        send,
      },
    } as never;

    render(
      <MemoryRouter initialEntries={['/login']}>
        <Login />
      </MemoryRouter>
    );

    fireEvent.click(screen.getByRole('button', { name: 'auth.login.openBrowserReset' }));

    expect(startBrowserLogin).not.toHaveBeenCalled();
    expect(send).toHaveBeenCalledTimes(1);
    expect(send.mock.calls[0][0]).toBe('open-external-url');
    expect(String(send.mock.calls[0][1])).toContain('/forgot-password?desktop=1');
    expect(String(send.mock.calls[0][1])).not.toContain('attempt_id=');
  });
});
