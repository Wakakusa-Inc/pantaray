import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { supabase, supabaseAuthStorageKey } from '../lib/supabase';
import { useI18n } from '@/context/useI18n';
import { BrandWordmark } from '@/components/BrandWordmark';
import { validatePassword } from '@/lib/passwordPolicy';
import {
  clearPasswordRecoverySessionMarker,
  getBrowserLocalStorage,
  getBrowserSessionStorage,
  getPasswordRecoveryCode,
  getPasswordRecoveryRedirectPendingKind,
  hasPasswordRecoveryCodeVerifier,
  hasVerifiedPasswordRecoverySession,
  markPasswordRecoverySessionVerified,
  type PasswordRecoverySessionStatus,
} from '@/lib/passwordRecoverySession';

// Define message types
type MessageType = 'success' | 'error' | null;

interface PkceRecoveryExchange {
  code: string;
  promise: Promise<boolean>;
}

let pkceRecoveryExchange: PkceRecoveryExchange | null = null;

function getCurrentPasswordRecoveryCode(): string | null {
  if (typeof window === 'undefined') {
    return null;
  }
  return getPasswordRecoveryCode(window.location.href);
}

function removePasswordRecoveryCodeFromUrl(): void {
  if (typeof window === 'undefined') {
    return;
  }
  const url = new URL(window.location.href);
  url.searchParams.delete('code');
  window.history.replaceState(window.history.state, '', url.toString());
}

function exchangePkceRecoveryCodeOnce(code: string): Promise<boolean> {
  if (pkceRecoveryExchange?.code === code) {
    return pkceRecoveryExchange.promise;
  }

  if (!hasPasswordRecoveryCodeVerifier(getBrowserLocalStorage(), supabaseAuthStorageKey)) {
    return Promise.resolve(false);
  }

  const promise = supabase.auth
    .exchangeCodeForSession(code)
    .then(({ data, error }) => !error && Boolean(data.session))
    .catch(() => false);
  pkceRecoveryExchange = { code, promise };
  void promise.then((isRecoverySession) => {
    if (
      !isRecoverySession &&
      pkceRecoveryExchange?.code === code &&
      pkceRecoveryExchange.promise === promise
    ) {
      pkceRecoveryExchange = null;
    }
  });
  return promise;
}

const ResetPassword: React.FC = () => {
  const { t } = useI18n();
  const [password, setPassword] = useState<string>('');
  const [confirmPassword, setConfirmPassword] = useState<string>('');
  const [message, setMessage] = useState<string>('');
  const [messageType, setMessageType] = useState<MessageType>(null);
  const [passwordError, setPasswordError] = useState<string>('');
  const [isLoading, setIsLoading] = useState<boolean>(false);
  const [recoveryStatus, setRecoveryStatus] = useState<PasswordRecoverySessionStatus>('checking');
  const navigate = useNavigate();

  useEffect(() => {
    let cancelled = false;
    let subscription: { unsubscribe: () => void } | null = null;
    const storage = getBrowserSessionStorage();

    const markRecoveryInvalid = () => {
      if (cancelled) {
        return;
      }

      clearPasswordRecoverySessionMarker(storage);
      setRecoveryStatus('invalid');
      setMessageType('error');
      setMessage(t('auth.error.resetLinkInvalid'));
    };

    const verifyRecoverySession = async () => {
      const {
        data: { session },
        error,
      } = await supabase.auth.getSession();

      if (cancelled) {
        return;
      }

      if (error || !session || !hasVerifiedPasswordRecoverySession(storage)) {
        markRecoveryInvalid();
        return;
      }

      setRecoveryStatus('ready');
    };

    const verifyPkceRecoveryCode = async () => {
      const code = getCurrentPasswordRecoveryCode();
      if (!code) {
        markRecoveryInvalid();
        return;
      }

      const isRecoverySession = await exchangePkceRecoveryCodeOnce(code);
      if (cancelled) {
        return;
      }

      removePasswordRecoveryCodeFromUrl();

      if (!isRecoverySession) {
        markRecoveryInvalid();
        return;
      }

      markPasswordRecoverySessionVerified(storage);
      await verifyRecoverySession();
    };

    if (hasVerifiedPasswordRecoverySession(storage)) {
      void verifyRecoverySession();
      return () => {
        cancelled = true;
      };
    }

    const pendingKind = getPasswordRecoveryRedirectPendingKind(storage);
    if (!pendingKind) {
      markRecoveryInvalid();
      return () => {
        cancelled = true;
      };
    }

    if (pendingKind === 'code') {
      void verifyPkceRecoveryCode();
      return () => {
        cancelled = true;
      };
    }

    const {
      data: { subscription: authSubscription },
    } = supabase.auth.onAuthStateChange((event, session) => {
      if (event === 'PASSWORD_RECOVERY' && session) {
        markPasswordRecoverySessionVerified(storage);
        void verifyRecoverySession();
      }
    });
    subscription = authSubscription;

    if (hasVerifiedPasswordRecoverySession(storage)) {
      void verifyRecoverySession();
    }

    return () => {
      cancelled = true;
      subscription?.unsubscribe();
    };
  }, [t]);

  const handleResetPassword = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsLoading(true);
    setMessage('');
    setPasswordError('');

    // Password validation
    const pw = validatePassword(password);
    if (!pw.ok) {
      if (pw.reason === 'spaces' || pw.missing.includes('no_spaces')) {
        setPasswordError(t('auth.error.passwordNoSpaces'));
        setIsLoading(false);
        return;
      }
      const tokens: string[] = [];
      if (pw.missing.includes('min_length')) tokens.push(t('auth.passwordToken.minLengthShort'));
      if (pw.missing.includes('uppercase')) tokens.push(t('auth.passwordToken.uppercaseShort'));
      if (pw.missing.includes('lowercase')) tokens.push(t('auth.passwordToken.lowercaseShort'));
      if (pw.missing.includes('number')) tokens.push(t('auth.passwordToken.numberShort'));
      if (pw.missing.includes('special')) tokens.push(t('auth.passwordToken.specialShort'));
      setPasswordError(
        tokens.length
          ? t('auth.error.passwordNeed', { tokens: tokens.join(' ') })
          : t('auth.error.generic')
      );
      setIsLoading(false);
      return;
    }

    if (password !== confirmPassword) {
      setPasswordError(t('auth.error.passwordMismatch'));
      setIsLoading(false);
      return;
    }

    try {
      const storage = getBrowserSessionStorage();
      const hasVerifiedRecoverySession = hasVerifiedPasswordRecoverySession(storage);
      const {
        data: { session },
        error: sessionError,
      } = await supabase.auth.getSession();

      if (sessionError || !session || !hasVerifiedRecoverySession || recoveryStatus !== 'ready') {
        clearPasswordRecoverySessionMarker(storage);
        setMessageType('error');
        setMessage(t('auth.error.resetLinkInvalid'));
        setIsLoading(false);
        return;
      }

      // リダイレクトをブロックするフラグを設定
      localStorage.setItem('skipAuthRedirect', 'true');

      // パスワード更新
      const { error } = await supabase.auth.updateUser({
        password,
      });

      if (error) {
        setMessageType('error');
        console.error('Password update error:', error);
        setMessage(t('auth.error.generic'));
        localStorage.removeItem('skipAuthRedirect');
      } else {
        setMessageType('success');
        setMessage(t('auth.message.passwordUpdated'));

        const { error: signOutError } = await supabase.auth.signOut({ scope: 'local' });
        const {
          data: { session: remainingSession },
          error: remainingSessionError,
        } = await supabase.auth.getSession();

        if (signOutError || remainingSessionError || remainingSession) {
          console.error('Password reset sign-out failed:', signOutError ?? remainingSessionError);
          setMessageType('error');
          setMessage(t('auth.error.generic'));
          localStorage.removeItem('skipAuthRedirect');
          return;
        }

        clearPasswordRecoverySessionMarker(storage);
        // 成功画面へリダイレクト
        setTimeout(() => {
          navigate('/password-reset-success');
          localStorage.removeItem('skipAuthRedirect');
        }, 3000);
      }
    } catch (error: unknown) {
      setMessageType('error');
      console.error('Reset password unexpected error:', error);
      setMessage(t('auth.error.generic'));
      localStorage.removeItem('skipAuthRedirect');
    } finally {
      setIsLoading(false);
    }
  };

  // Get message class name
  const getMessageClassName = (type: MessageType): string => {
    switch (type) {
      case 'success':
        return 'auth-message--success';
      case 'error':
        return 'auth-message--error';
      default:
        return '';
    }
  };

  return (
    <div className="auth-container">
      <div className="app-drag-handle"></div>
      <div className="auth-form">
        <BrandWordmark className="brand-wordmark--auth" />
        <h2>{t('auth.reset.title')}</h2>
        <form onSubmit={handleResetPassword} noValidate>
          <div>
            <input
              type="password"
              placeholder={t('auth.form.passwordNewPlaceholder')}
              value={password}
              onChange={(e) => {
                setPassword(e.target.value);
                setPasswordError('');
              }}
              required
              className="auth-input"
              name="password"
              id="password"
              autoComplete="new-password"
            />
          </div>
          <div>
            <input
              type="password"
              placeholder={t('auth.form.passwordConfirmPlaceholder')}
              value={confirmPassword}
              onChange={(e) => {
                setConfirmPassword(e.target.value);
                setPasswordError('');
              }}
              required
              className="auth-input"
              name="confirmPassword"
              id="confirmPassword"
              autoComplete="new-password"
            />
          </div>
          <button
            type="submit"
            disabled={isLoading || recoveryStatus !== 'ready'}
            className="auth-button"
          >
            {isLoading
              ? t('auth.form.updatePasswordButtonLoading')
              : t('auth.form.updatePasswordButton')}
          </button>
          <p
            className={[
              'auth-message',
              !passwordError ? 'auth-message--empty' : '',
              'auth-message--error',
            ]
              .filter(Boolean)
              .join(' ')}
            aria-hidden={!passwordError}
          >
            {passwordError}
          </p>
          {message && (
            <p className={`auth-message ${getMessageClassName(messageType)}`}>{message}</p>
          )}
        </form>
      </div>
    </div>
  );
};

export default ResetPassword;
