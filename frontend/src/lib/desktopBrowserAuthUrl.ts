import { buildWebAppUrl, type WebAppRoute } from '@/config/webAppUrl';

type BrowserLoginAttempt = {
  attempt_id?: string;
  code_challenge?: string;
  loopback_redirect_url?: string;
};

function normalizeOptionalString(value: unknown): string | null {
  if (typeof value !== 'string') {
    return null;
  }
  const normalized = value.trim();
  return normalized ? normalized : null;
}

export function buildDesktopBrowserAuthUrl(
  route: WebAppRoute,
  attempt: BrowserLoginAttempt | null | undefined
): string {
  const params: Record<string, string> = { desktop: '1' };
  const attemptId = normalizeOptionalString(attempt?.attempt_id);
  const codeChallenge = normalizeOptionalString(attempt?.code_challenge);
  const loopbackRedirectUrl = normalizeOptionalString(attempt?.loopback_redirect_url);

  if (attemptId !== null && codeChallenge !== null) {
    params.attempt_id = attemptId;
    params.code_challenge = codeChallenge;
  }
  if (loopbackRedirectUrl !== null) {
    params.loopback_redirect_url = loopbackRedirectUrl;
  }
  return buildWebAppUrl(route, params);
}
