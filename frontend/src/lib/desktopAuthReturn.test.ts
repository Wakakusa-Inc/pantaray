import { describe, expect, it, vi, afterEach } from 'vitest';
import type { Session } from '@supabase/supabase-js';

import {
  completeDesktopAuthReturn,
  getDesktopAuthReturnParams,
  type DesktopAuthReturnParams,
} from './desktopAuthReturn';

const baseParams: DesktopAuthReturnParams = {
  isDesktopReturn: true,
  isDesktopReturnCompleted: false,
  attemptId: 'attempt-1',
  codeChallenge: 'challenge-1',
  loopbackRedirectUrl: 'http://127.0.0.1:32100/auth/callback?state=state-1',
};

const session = {
  access_token: 'access-token',
  refresh_token: 'refresh-token',
} as Session;

describe('desktopAuthReturn', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it('parses desktop return params from browser auth URL search', () => {
    const params = getDesktopAuthReturnParams(
      '?desktop=1&attempt_id=A&code_challenge=C&loopback_redirect_url=' +
        encodeURIComponent('http://127.0.0.1:32100/auth/callback?state=S')
    );

    expect(params).toEqual({
      isDesktopReturn: true,
      isDesktopReturnCompleted: false,
      attemptId: 'A',
      codeChallenge: 'C',
      loopbackRedirectUrl: 'http://127.0.0.1:32100/auth/callback?state=S',
    });
  });

  it('issues a desktop auth exchange and prefers loopback return URL', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(
        async () =>
          new Response(JSON.stringify({ ok: true, exchange_code: 'exchange-1' }), {
            status: 200,
            headers: { 'Content-Type': 'application/json' },
          })
      )
    );

    const result = await completeDesktopAuthReturn(baseParams, session);

    expect(result).toEqual({
      ok: true,
      returnUrl:
        'http://127.0.0.1:32100/auth/callback?state=state-1&attempt_id=attempt-1&exchange_code=exchange-1',
    });
  });

  it('returns to the desktop loopback port even when another port is requested', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(
        async () =>
          new Response(JSON.stringify({ ok: true, exchange_code: 'exchange-1' }), {
            status: 200,
            headers: { 'Content-Type': 'application/json' },
          })
      )
    );

    const result = await completeDesktopAuthReturn(
      { ...baseParams, loopbackRedirectUrl: 'http://127.0.0.1:43121/auth/callback?state=state-1' },
      session
    );

    expect(result).toEqual({
      ok: true,
      returnUrl:
        'http://127.0.0.1:32100/auth/callback?state=state-1&attempt_id=attempt-1&exchange_code=exchange-1',
    });
  });

  it('falls back to the deep link when loopback_redirect_url carries no state', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(
        async () =>
          new Response(JSON.stringify({ ok: true, exchange_code: 'exchange-1' }), {
            status: 200,
            headers: { 'Content-Type': 'application/json' },
          })
      )
    );

    const result = await completeDesktopAuthReturn(
      { ...baseParams, loopbackRedirectUrl: 'https://attacker.example/auth/callback' },
      session
    );

    expect(result).toEqual({
      ok: true,
      returnUrl: 'pantaray://auth?attempt_id=attempt-1&exchange_code=exchange-1',
    });
  });

  it('does not create a desktop exchange when attempt params are missing', async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal('fetch', fetchMock);

    const result = await completeDesktopAuthReturn(
      { ...baseParams, attemptId: '', codeChallenge: '' },
      session
    );

    expect(result).toEqual({ ok: true, returnUrl: null });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('returns a visible error when desktop auth issue fails', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(
        async () =>
          new Response(JSON.stringify({ ok: false, error: 'rate limited' }), {
            status: 429,
            headers: { 'Content-Type': 'application/json' },
          })
      )
    );

    const result = await completeDesktopAuthReturn(baseParams, session);

    expect(result).toEqual({ ok: false, error: 'rate limited' });
  });
});
