import type { Session } from '@supabase/supabase-js';

export type DesktopAuthReturnParams = {
  isDesktopReturn: boolean;
  isDesktopReturnCompleted: boolean;
  attemptId: string;
  codeChallenge: string;
  loopbackRedirectUrl: string;
};

type DesktopAuthIssueResponse = {
  ok: boolean;
  exchangeCode: string;
  error: string | null;
};

export type DesktopAuthReturnResult =
  | { ok: true; returnUrl: string | null }
  | { ok: false; error: string };

function normalizeOptionalString(value: string | null): string {
  return String(value || '').trim();
}

function parseIssueResponse(value: unknown): DesktopAuthIssueResponse | null {
  if (!value || typeof value !== 'object') {
    return null;
  }
  const record = value as { ok?: unknown; exchange_code?: unknown; error?: unknown };
  return {
    ok: record.ok === true,
    exchangeCode: typeof record.exchange_code === 'string' ? record.exchange_code.trim() : '',
    error: typeof record.error === 'string' ? record.error : null,
  };
}

function buildIssueUrl(): string {
  return `${(import.meta.env.VITE_SUPABASE_URL || '').replace(/\/$/, '')}/functions/v1/desktop_auth/issue`;
}

function buildIssueHeaders(accessToken: string): HeadersInit {
  const publishableKey = String(import.meta.env.VITE_SUPABASE_PUBLISHABLE_KEY || '').trim();
  return {
    'Content-Type': 'application/json',
    ...(publishableKey ? { apikey: publishableKey } : {}),
    Authorization: `Bearer ${accessToken}`,
  };
}

// デスクトップの loopback サーバーの待ち受け先。frontend/electron/src/main.ts と揃える。
const DESKTOP_LOOPBACK_CALLBACK_URL = 'http://127.0.0.1:32100/auth/callback';

// 戻り先は上の固定 URL とし、渡された loopback_redirect_url からは state だけを引き継ぐ。
// URL をそのまま使うと、ローカルの別プロセスが自分のポートを戻り先に指定できてしまう。
function buildLoopbackReturnUrl(
  loopbackRedirectUrl: string,
  attemptId: string,
  exchangeCode: string
): string | null {
  if (!loopbackRedirectUrl) {
    return null;
  }

  let state = '';
  try {
    state = normalizeOptionalString(new URL(loopbackRedirectUrl).searchParams.get('state'));
  } catch {
    return null;
  }
  if (!state) {
    return null;
  }

  const url = new URL(DESKTOP_LOOPBACK_CALLBACK_URL);
  url.searchParams.set('state', state);
  url.searchParams.set('attempt_id', attemptId);
  url.searchParams.set('exchange_code', exchangeCode);
  return url.toString();
}

export function getDesktopAuthReturnParams(search: string): DesktopAuthReturnParams {
  const params = new URLSearchParams(search || '');
  const desktopParam = normalizeOptionalString(params.get('desktop'));
  const desktopReturnParam = normalizeOptionalString(params.get('desktop_return'));
  return {
    isDesktopReturn: desktopParam === '1' || desktopParam === 'true',
    isDesktopReturnCompleted: desktopReturnParam === '1' || desktopReturnParam === 'true',
    attemptId: normalizeOptionalString(params.get('attempt_id')),
    codeChallenge: normalizeOptionalString(params.get('code_challenge')),
    loopbackRedirectUrl: normalizeOptionalString(params.get('loopback_redirect_url')),
  };
}

export async function completeDesktopAuthReturn(
  params: DesktopAuthReturnParams,
  session: Session | null
): Promise<DesktopAuthReturnResult> {
  if (!params.isDesktopReturn) {
    return { ok: true, returnUrl: null };
  }
  if (!params.attemptId || !params.codeChallenge) {
    return { ok: true, returnUrl: null };
  }
  if (!session?.access_token || !session?.refresh_token) {
    return { ok: false, error: 'Supabase session tokens are missing.' };
  }

  const issueResp = await fetch(buildIssueUrl(), {
    method: 'POST',
    headers: buildIssueHeaders(session.access_token),
    body: JSON.stringify({
      attempt_id: params.attemptId,
      code_challenge: params.codeChallenge,
      code_challenge_method: 'S256',
      tokens: {
        access_token: session.access_token,
        refresh_token: session.refresh_token,
      },
    }),
  });
  const issueJson = parseIssueResponse(await issueResp.json().catch(() => null));
  if (!issueResp.ok || !issueJson?.ok) {
    return {
      ok: false,
      error: issueJson?.error || `desktop auth issue failed (${issueResp.status})`,
    };
  }
  if (!issueJson.exchangeCode) {
    return { ok: false, error: 'desktop auth issue response is missing exchange_code.' };
  }

  const loopbackUrl = buildLoopbackReturnUrl(
    params.loopbackRedirectUrl,
    params.attemptId,
    issueJson.exchangeCode
  );
  if (loopbackUrl) {
    return { ok: true, returnUrl: loopbackUrl };
  }

  return {
    ok: true,
    returnUrl:
      `pantaray://auth?attempt_id=${encodeURIComponent(params.attemptId)}` +
      `&exchange_code=${encodeURIComponent(issueJson.exchangeCode)}`,
  };
}
