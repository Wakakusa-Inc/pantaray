import { act, cleanup, renderHook } from '@testing-library/react';
import { AuthError, type AuthChangeEvent, type Session } from '@supabase/supabase-js';
import { afterEach, describe, expect, it, vi } from 'vitest';

import type { AuthState } from '../../electron/src/ipc/context';
import { useAuth } from '../hooks/useAuth';
import { AuthProvider } from './AuthContext';

vi.mock('../../electron/src/auth/accountLoginFeature', () => ({
  PANTARAY_ACCOUNT_LOGIN_ENABLED: true,
}));

const webAuth = vi.hoisted(() => ({ getSession: vi.fn(), onAuthStateChange: vi.fn() }));
vi.mock('../lib/supabase', () => ({ getSupabase: () => ({ auth: webAuth }) }));

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: Error) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

function readyState(id: string): AuthState {
  return {
    authStatus: 'authenticated',
    isLoggedIn: true,
    user: { id },
    runtimeState: { status: 'ready', message: null, owner: { kind: 'account', id } },
  };
}

function installDesktop() {
  const initial = deferred<AuthState>();
  const listeners = new Set<(state: AuthState) => void>();
  Object.defineProperty(window, 'electron', {
    configurable: true,
    value: {
      auth: {
        getState: () => initial.promise,
        onStateChanged: (listener: (state: AuthState) => void) => {
          listeners.add(listener);
          return () => listeners.delete(listener);
        },
      },
    },
  });
  return { initial, listeners, emit: (state: AuthState) => listeners.forEach((fn) => fn(state)) };
}

function webSession(id: string): Session {
  return {
    access_token: 'test-access',
    refresh_token: 'test-refresh',
    expires_in: 3600,
    token_type: 'bearer',
    user: {
      id,
      aud: 'authenticated',
      app_metadata: {},
      user_metadata: {},
      created_at: '2026-09-17T00:00:00Z',
    },
  };
}

function installWeb() {
  const initial = deferred<{ data: { session: Session | null }; error: AuthError | null }>();
  const listeners = new Set<(event: AuthChangeEvent, session: Session | null) => void>();
  webAuth.getSession.mockReturnValue(initial.promise);
  webAuth.onAuthStateChange.mockImplementation((listener) => {
    listeners.add(listener);
    return { data: { subscription: { unsubscribe: () => listeners.delete(listener) } } };
  });
  return {
    initial,
    listeners,
    emit: (session: Session | null) => listeners.forEach((fn) => fn('SIGNED_IN', session)),
  };
}

describe('AuthProvider initialization', () => {
  afterEach(() => {
    cleanup();
    delete window.electron;
    vi.restoreAllMocks();
    vi.resetAllMocks();
  });

  it('keeps the newer desktop owner when the initial snapshot arrives late', async () => {
    const desktop = installDesktop();
    const { result } = renderHook(useAuth, { wrapper: AuthProvider });
    act(() => desktop.emit(readyState('owner-b')));
    await act(async () => desktop.initial.resolve(readyState('owner-a')));
    expect(result.current.user?.id).toBe('owner-b');
    expect(result.current.runtimeState.owner?.id).toBe('owner-b');
    expect(result.current.loading).toBe(false);
  });

  it('unsubscribes desktop notifications before a pending snapshot settles', async () => {
    const desktop = installDesktop();
    const { unmount } = renderHook(useAuth, { wrapper: AuthProvider });
    expect(desktop.listeners.size).toBe(1);
    unmount();
    expect(desktop.listeners.size).toBe(0);
    await act(async () => desktop.initial.resolve(readyState('owner-a')));
    expect(desktop.listeners.size).toBe(0);
  });

  it('accepts a guest snapshot without requiring a cloud user', async () => {
    const desktop = installDesktop();
    const { result } = renderHook(useAuth, { wrapper: AuthProvider });
    await act(async () =>
      desktop.initial.resolve({
        authStatus: 'unauthenticated',
        isLoggedIn: false,
        user: null,
        runtimeState: { status: 'ready', message: null, owner: { kind: 'guest', id: 'guest' } },
      })
    );
    expect(result.current.user).toBeNull();
    expect(result.current.runtimeState.owner).toEqual({ kind: 'guest', id: 'guest' });
    expect(result.current.authStatus).toBe('unauthenticated');
    expect(result.current.loading).toBe(false);
  });

  it('preserves cloud expiry independently of a degraded local runtime', async () => {
    const desktop = installDesktop();
    const { result } = renderHook(useAuth, { wrapper: AuthProvider });
    act(() =>
      desktop.emit({
        authStatus: 'expired',
        isLoggedIn: false,
        user: null,
        runtimeState: { status: 'degraded', message: 'helper unavailable', owner: null },
      })
    );
    expect(result.current.user).toBeNull();
    expect(result.current.runtimeState.owner).toBeNull();
    expect(result.current.authStatus).toBe('expired');
    act(() =>
      desktop.emit({
        authStatus: 'unauthenticated',
        isLoggedIn: false,
        user: null,
        runtimeState: { status: 'ready', message: null, owner: { kind: 'guest', id: 'guest' } },
      })
    );
    expect(result.current.authStatus).toBe('unauthenticated');
  });

  it('does not let a stale desktop failure end newer initialization', async () => {
    const desktop = installDesktop();
    vi.spyOn(console, 'error').mockImplementation(() => undefined);
    const { result } = renderHook(useAuth, { wrapper: AuthProvider });
    act(() =>
      desktop.emit({
        ...readyState('owner-b'),
        authStatus: 'initializing',
        runtimeState: { status: 'syncing', message: null, owner: null },
      })
    );
    await act(async () => desktop.initial.reject(new Error('IPC unavailable')));
    expect(result.current.loading).toBe(true);
    act(() => desktop.emit(readyState('owner-b')));
    expect(result.current.loading).toBe(false);
    expect(result.current.runtimeState.owner?.id).toBe('owner-b');
  });

  it('receives web auth changes during the initial read and ignores its stale result', async () => {
    const web = installWeb();
    const { result } = renderHook(useAuth, { wrapper: AuthProvider });
    act(() => web.emit(webSession('owner-b')));
    expect(result.current.user?.id).toBe('owner-b');
    expect(result.current.loading).toBe(false);
    await act(async () => web.initial.resolve({ data: { session: null }, error: null }));
    expect(result.current.session?.user.id).toBe('owner-b');
    expect(result.current.authStatus).toBe('authenticated');
    act(() => web.emit(null));
    expect(result.current.authStatus).toBe('unauthenticated');
  });

  it('unsubscribes web notifications while the initial read is pending', async () => {
    const web = installWeb();
    const { unmount } = renderHook(useAuth, { wrapper: AuthProvider });
    expect(web.listeners.size).toBe(1);
    unmount();
    await act(async () => web.initial.resolve({ data: { session: null }, error: null }));
    expect(web.listeners.size).toBe(0);
  });

  it('can recover through web notifications after the initial read rejects', async () => {
    const web = installWeb();
    vi.spyOn(console, 'error').mockImplementation(() => undefined);
    const { result } = renderHook(useAuth, { wrapper: AuthProvider });
    await act(async () => web.initial.reject(new AuthError('Session unavailable')));
    expect(result.current.loading).toBe(false);
    act(() => web.emit(webSession('owner-b')));
    expect(result.current.user?.id).toBe('owner-b');
    expect(result.current.session?.user.id).toBe('owner-b');
    expect(result.current.authStatus).toBe('authenticated');
    act(() => web.emit(null));
    expect(result.current.authStatus).toBe('unauthenticated');
  });
});
