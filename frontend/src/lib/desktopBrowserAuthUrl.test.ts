import { describe, expect, it, vi } from 'vitest';

vi.mock('@/config/webAppUrl', () => ({
  buildWebAppUrl: (route: string, params?: Record<string, string>) => {
    const search = new URLSearchParams(params ?? {}).toString();
    return `https://example.test/${route}${search ? `?${search}` : ''}`;
  },
}));

import { buildDesktopBrowserAuthUrl } from './desktopBrowserAuthUrl';

describe('buildDesktopBrowserAuthUrl', () => {
  it('includes loopback_redirect_url for desktop browser auth flows', () => {
    const url = buildDesktopBrowserAuthUrl('signup', {
      attempt_id: 'A1',
      code_challenge: 'C1',
      loopback_redirect_url: 'http://127.0.0.1:32100/auth/callback?state=S1',
    });

    expect(url).toContain('/signup?');
    expect(url).toContain('desktop=1');
    expect(url).toContain('attempt_id=A1');
    expect(url).toContain('code_challenge=C1');
    expect(url).toContain(encodeURIComponent('http://127.0.0.1:32100/auth/callback?state=S1'));
  });
});
