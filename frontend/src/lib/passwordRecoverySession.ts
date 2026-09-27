const PASSWORD_RECOVERY_SESSION_MARKER_KEY = 'pantaray_password_recovery_session';
const PASSWORD_RECOVERY_SESSION_PENDING_IMPLICIT_VALUE = 'pending_implicit';
const PASSWORD_RECOVERY_SESSION_PENDING_CODE_VALUE = 'pending_code';
const PASSWORD_RECOVERY_SESSION_VERIFIED_VALUE = 'verified';
const PASSWORD_RECOVERY_CODE_VERIFIER_SUFFIX = '/PASSWORD_RECOVERY';

export type PasswordRecoverySessionStatus = 'checking' | 'ready' | 'invalid';
export type PasswordRecoveryRedirectKind = 'implicit' | 'code';

function isResetPasswordPath(pathname: string): boolean {
  return pathname === '/reset-password';
}

function getPasswordRecoveryParamKind(
  params: URLSearchParams
): PasswordRecoveryRedirectKind | null {
  if (params.has('error') || params.has('error_description') || params.has('error_code')) {
    return null;
  }

  const hasImplicitTokens = Boolean(params.get('access_token') && params.get('refresh_token'));
  const hasPkceCode = Boolean(params.get('code'));
  const isRecoveryRedirect = params.get('type') === 'recovery';

  if (isRecoveryRedirect && hasImplicitTokens) {
    return 'implicit';
  }
  if (hasPkceCode) {
    return 'code';
  }
  return null;
}

export function getPasswordRecoveryRedirectKind(
  urlString: string
): PasswordRecoveryRedirectKind | null {
  try {
    const url = new URL(urlString);
    if (!isResetPasswordPath(url.pathname)) {
      return null;
    }

    const hashParams = new URLSearchParams(url.hash.startsWith('#') ? url.hash.slice(1) : url.hash);
    return (
      getPasswordRecoveryParamKind(hashParams) || getPasswordRecoveryParamKind(url.searchParams)
    );
  } catch {
    return null;
  }
}

export function isPasswordRecoveryRedirectUrl(urlString: string): boolean {
  return getPasswordRecoveryRedirectKind(urlString) !== null;
}

export function getPasswordRecoveryCode(urlString: string): string | null {
  try {
    const url = new URL(urlString);
    if (!isResetPasswordPath(url.pathname)) {
      return null;
    }
    if (url.searchParams.has('error') || url.searchParams.has('error_description')) {
      return null;
    }

    const code = url.searchParams.get('code');
    return code && code.trim() ? code : null;
  } catch {
    return null;
  }
}

export function hasPasswordRecoveryCodeVerifier(
  storage: Storage | null,
  authStorageKey: string
): boolean {
  if (!authStorageKey.trim()) {
    return false;
  }
  try {
    return Boolean(
      storage
        ?.getItem(`${authStorageKey}-code-verifier`)
        ?.endsWith(PASSWORD_RECOVERY_CODE_VERIFIER_SUFFIX)
    );
  } catch {
    return false;
  }
}

export function getBrowserSessionStorage(): Storage | null {
  if (typeof window === 'undefined') {
    return null;
  }

  try {
    return window.sessionStorage;
  } catch {
    return null;
  }
}

export function getBrowserLocalStorage(): Storage | null {
  if (typeof window === 'undefined') {
    return null;
  }

  try {
    return window.localStorage;
  } catch {
    return null;
  }
}

function getRecoveryMarkerValue(storage: Storage | null): string | null {
  try {
    return storage?.getItem(PASSWORD_RECOVERY_SESSION_MARKER_KEY) ?? null;
  } catch {
    return null;
  }
}

function setRecoveryMarkerValue(storage: Storage | null, value: string): void {
  try {
    storage?.setItem(PASSWORD_RECOVERY_SESSION_MARKER_KEY, value);
  } catch {
    // Storage can be exposed but blocked. Treat it as unavailable.
  }
}

export function markPasswordRecoveryRedirectPending(
  storage: Storage | null,
  kind: PasswordRecoveryRedirectKind
): void {
  setRecoveryMarkerValue(
    storage,
    kind === 'implicit'
      ? PASSWORD_RECOVERY_SESSION_PENDING_IMPLICIT_VALUE
      : PASSWORD_RECOVERY_SESSION_PENDING_CODE_VALUE
  );
}

export function markPasswordRecoverySessionVerified(storage: Storage | null): void {
  setRecoveryMarkerValue(storage, PASSWORD_RECOVERY_SESSION_VERIFIED_VALUE);
}

export function clearPasswordRecoverySessionMarker(storage: Storage | null): void {
  try {
    storage?.removeItem(PASSWORD_RECOVERY_SESSION_MARKER_KEY);
  } catch {
    // Storage can be exposed but blocked. Treat it as unavailable.
  }
}

export function hasPasswordRecoveryRedirectPending(storage: Storage | null): boolean {
  return getPasswordRecoveryRedirectPendingKind(storage) !== null;
}

export function getPasswordRecoveryRedirectPendingKind(
  storage: Storage | null
): PasswordRecoveryRedirectKind | null {
  const marker = getRecoveryMarkerValue(storage);
  if (marker === PASSWORD_RECOVERY_SESSION_PENDING_IMPLICIT_VALUE) {
    return 'implicit';
  }
  if (marker === PASSWORD_RECOVERY_SESSION_PENDING_CODE_VALUE) {
    return 'code';
  }
  return null;
}

export function hasVerifiedPasswordRecoverySession(storage: Storage | null): boolean {
  return getRecoveryMarkerValue(storage) === PASSWORD_RECOVERY_SESSION_VERIFIED_VALUE;
}
