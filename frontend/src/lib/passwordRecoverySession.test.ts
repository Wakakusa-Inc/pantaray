import { describe, expect, it } from 'vitest';
import {
  clearPasswordRecoverySessionMarker,
  getPasswordRecoveryCode,
  getPasswordRecoveryRedirectKind,
  getPasswordRecoveryRedirectPendingKind,
  hasPasswordRecoveryCodeVerifier,
  hasPasswordRecoveryRedirectPending,
  hasVerifiedPasswordRecoverySession,
  isPasswordRecoveryRedirectUrl,
  markPasswordRecoveryRedirectPending,
  markPasswordRecoverySessionVerified,
} from './passwordRecoverySession';

class MemoryStorage implements Storage {
  private values = new Map<string, string>();

  get length(): number {
    return this.values.size;
  }

  clear(): void {
    this.values.clear();
  }

  getItem(key: string): string | null {
    return this.values.get(key) ?? null;
  }

  key(index: number): string | null {
    return Array.from(this.values.keys())[index] ?? null;
  }

  removeItem(key: string): void {
    this.values.delete(key);
  }

  setItem(key: string, value: string): void {
    this.values.set(key, value);
  }
}

describe('passwordRecoverySession', () => {
  it('recognizes valid implicit and PKCE recovery redirect URLs without accepting error URLs', () => {
    expect(
      isPasswordRecoveryRedirectUrl(
        'https://example.test/reset-password#access_token=AT&refresh_token=RT&type=recovery'
      )
    ).toBe(true);
    expect(isPasswordRecoveryRedirectUrl('https://example.test/reset-password?code=C')).toBe(true);
    expect(
      getPasswordRecoveryRedirectKind(
        'https://example.test/reset-password#access_token=AT&refresh_token=RT&type=recovery'
      )
    ).toBe('implicit');
    expect(getPasswordRecoveryRedirectKind('https://example.test/reset-password?code=C')).toBe(
      'code'
    );
    expect(
      isPasswordRecoveryRedirectUrl(
        'https://example.test/reset-password#error=access_denied&type=recovery'
      )
    ).toBe(false);
    expect(isPasswordRecoveryRedirectUrl('https://example.test/reset-password#type=signup')).toBe(
      false
    );
    expect(isPasswordRecoveryRedirectUrl('https://example.test/login?code=C')).toBe(false);
    expect(getPasswordRecoveryRedirectKind('https://example.test/login?code=C')).toBeNull();
    expect(getPasswordRecoveryCode('https://example.test/reset-password?code=C')).toBe('C');
    expect(
      getPasswordRecoveryCode('https://example.test/reset-password?error=access_denied&code=C')
    ).toBeNull();
  });

  it('separates pending redirects from verified recovery sessions without storing tokens', () => {
    const storage = new MemoryStorage();

    expect(hasPasswordRecoveryRedirectPending(storage)).toBe(false);
    expect(hasVerifiedPasswordRecoverySession(storage)).toBe(false);

    markPasswordRecoveryRedirectPending(storage, 'implicit');

    expect(storage.length).toBe(1);
    expect(hasPasswordRecoveryRedirectPending(storage)).toBe(true);
    expect(getPasswordRecoveryRedirectPendingKind(storage)).toBe('implicit');
    expect(hasVerifiedPasswordRecoverySession(storage)).toBe(false);

    markPasswordRecoverySessionVerified(storage);

    expect(storage.length).toBe(1);
    expect(hasPasswordRecoveryRedirectPending(storage)).toBe(false);
    expect(hasVerifiedPasswordRecoverySession(storage)).toBe(true);

    clearPasswordRecoverySessionMarker(storage);

    expect(storage.length).toBe(0);
    expect(hasPasswordRecoveryRedirectPending(storage)).toBe(false);
    expect(hasVerifiedPasswordRecoverySession(storage)).toBe(false);
  });

  it('records PKCE pending redirects separately from implicit redirects', () => {
    const storage = new MemoryStorage();

    markPasswordRecoveryRedirectPending(storage, 'code');

    expect(hasPasswordRecoveryRedirectPending(storage)).toBe(true);
    expect(getPasswordRecoveryRedirectPendingKind(storage)).toBe('code');
    expect(hasVerifiedPasswordRecoverySession(storage)).toBe(false);
  });

  it('accepts only Supabase password recovery code verifier markers', () => {
    const storage = new MemoryStorage();
    const storageKey = 'sb-project-auth-token';

    expect(hasPasswordRecoveryCodeVerifier(storage, storageKey)).toBe(false);

    storage.setItem(`${storageKey}-code-verifier`, 'verifier');
    expect(hasPasswordRecoveryCodeVerifier(storage, storageKey)).toBe(false);

    storage.setItem(`${storageKey}-code-verifier`, 'verifier/PASSWORD_RECOVERY');
    expect(hasPasswordRecoveryCodeVerifier(storage, storageKey)).toBe(true);
  });

  it('treats blocked storage as unavailable instead of throwing', () => {
    const blockedStorage = {
      get length() {
        return 0;
      },
      clear() {
        throw new Error('blocked');
      },
      getItem() {
        throw new Error('blocked');
      },
      key() {
        throw new Error('blocked');
      },
      removeItem() {
        throw new Error('blocked');
      },
      setItem() {
        throw new Error('blocked');
      },
    } satisfies Storage;

    expect(() => markPasswordRecoveryRedirectPending(blockedStorage, 'implicit')).not.toThrow();
    expect(() => markPasswordRecoverySessionVerified(blockedStorage)).not.toThrow();
    expect(() => clearPasswordRecoverySessionMarker(blockedStorage)).not.toThrow();
    expect(hasPasswordRecoveryRedirectPending(blockedStorage)).toBe(false);
    expect(hasVerifiedPasswordRecoverySession(blockedStorage)).toBe(false);
  });
});
