import { useState, FormEvent } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useAuth } from '../hooks/useAuth';
import { useI18n } from '@/context/useI18n';
import { BrandWordmark } from '@/components/BrandWordmark';
import { validatePassword } from '@/lib/passwordPolicy';
import { buildDesktopBrowserAuthUrl } from '@/lib/desktopBrowserAuthUrl';

export default function SignUp() {
  const { t } = useI18n();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [passwordConfirm, setPasswordConfirm] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const navigate = useNavigate();
  const { signUp } = useAuth();
  const isElectron = typeof window !== 'undefined' && Boolean(window.electron?.ipcRenderer);

  const openBrowserAuth = (route: 'login' | 'signup') => {
    try {
      const openWithParams = async (): Promise<void> => {
        const attempt = await window.electron?.auth?.startBrowserLogin?.(route);
        if (!attempt || attempt.ok !== true) {
          const rawErr = attempt?.error ? String(attempt.error) : '';
          const isPortInUse =
            rawErr.includes('EADDRINUSE') ||
            rawErr.toLowerCase().includes('address already in use');
          const msg = isPortInUse ? t('auth.error.loopbackPortInUse') : t('auth.error.generic');
          console.error('startBrowserLogin failed:', rawErr || '(unknown)');
          setError(msg);
          try {
            window.alert(msg);
          } catch {
            // no-op
          }
          return;
        }
        const url = buildDesktopBrowserAuthUrl(route, attempt);

        const ipcRenderer =
          typeof window !== 'undefined' ? window.electron?.ipcRenderer : undefined;
        if (ipcRenderer?.send) {
          ipcRenderer.send('open-external-url', url);
          return;
        }
        window.open(url, '_blank');
      };

      const ipcRenderer = typeof window !== 'undefined' ? window.electron?.ipcRenderer : undefined;
      if (ipcRenderer?.send) {
        void openWithParams();
        return;
      }
      void openWithParams();
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      console.error('openBrowserAuth failed:', msg);
      setError(t('auth.error.generic'));
      try {
        window.alert(t('auth.error.generic'));
      } catch {
        // no-op
      }
    }
  };

  if (isElectron) {
    return (
      <div className="auth-container">
        <div className="app-drag-handle"></div>
        <div className="auth-form auth-form--fixed-height">
          <BrandWordmark className="brand-wordmark--auth" />
          <h2>{t('auth.signup.title')}</h2>
          <p>{t('auth.signup.electronDescription')}</p>
          <button type="button" className="auth-button" onClick={() => openBrowserAuth('signup')}>
            {t('auth.signup.openBrowserSignup')}
          </button>
          {error && <p className="auth-message auth-message--error">{error}</p>}
          <div className="auth-footer">
            <button type="button" className="auth-link" onClick={() => openBrowserAuth('login')}>
              {t('auth.signup.backToLoginBrowser')}
            </button>
          </div>
        </div>
      </div>
    );
  }

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();

    // Reset all errors first
    setError('');

    // --- Validation ---
    // 重要: 「全部間違っている」場合は、まず email のエラーを出す（以降は評価しない）
    // Email validation
    if (!email) {
      // Check if email is empty
      setError(t('auth.error.emailRequired'));
      return;
    }
    if (!email.includes('@')) {
      setError(t('auth.error.emailNeedsAt'));
      return;
    }
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
      setError(t('auth.error.emailInvalid'));
      return;
    }

    // Password / Confirm validation（email がOKになってから）
    if (!password) {
      setError(t('auth.error.passwordRequired'));
      return;
    }

    // Password match validation
    if (password !== passwordConfirm) {
      setError(t('auth.error.passwordMismatch'));
      return;
    }

    // Password policy validation
    const pw = validatePassword(password);
    if (!pw.ok) {
      // 1行に収まる短い表記にする（切り捨てはしない）
      // 例: Need: 8+ A a 0-9 #
      if (pw.reason === 'spaces' || pw.missing.includes('no_spaces')) {
        setError(t('auth.error.passwordNoSpaces'));
        return;
      }
      const tokens: string[] = [];
      if (pw.missing.includes('min_length')) tokens.push(t('auth.passwordToken.minLengthShort'));
      if (pw.missing.includes('uppercase')) tokens.push(t('auth.passwordToken.uppercaseShort'));
      if (pw.missing.includes('lowercase')) tokens.push(t('auth.passwordToken.lowercaseShort'));
      if (pw.missing.includes('number')) tokens.push(t('auth.passwordToken.numberShort'));
      if (pw.missing.includes('special')) tokens.push(t('auth.passwordToken.specialShort'));
      setError(
        tokens.length
          ? t('auth.error.passwordNeed', { tokens: tokens.join(' ') })
          : t('auth.error.generic')
      );
      return;
    }

    // Proceed if no errors
    setLoading(true);

    try {
      // 実際のフォーム要素を取得 (削除)
      // const formElement = e.target as HTMLFormElement;

      const signUpResult = await signUp(email, password);

      if (signUpResult.status === 'already_registered') {
        setError(t('auth.error.signupAlreadyRegistered'));
        setLoading(false);
        return;
      }

      if (signUpResult.status === 'failed') {
        setError(t('auth.error.generic'));
        setLoading(false);
        return;
      }

      // 通常のページ遷移に戻す
      setTimeout(() => {
        navigate('/email-verification');
      }, 500); // 少し待ってから遷移 (メッセージ表示のため)
    } catch {
      setError(t('auth.error.generic'));
      setLoading(false);
    }
  };

  return (
    <div className="auth-container">
      <div className="app-drag-handle"></div>
      <div className="auth-form auth-form--fixed-height">
        <BrandWordmark className="brand-wordmark--auth" />
        <h2>{t('auth.signup.title')}</h2>
        <form onSubmit={handleSubmit} noValidate>
          {/* Email input */}
          <div>
            <input
              type="email"
              placeholder={t('auth.form.emailPlaceholder')}
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="auth-input"
              required
              disabled={loading}
              name="email"
              id="email"
              autoComplete="username email"
            />
          </div>

          {/* Password input */}
          <div>
            <input
              type="password"
              placeholder={t('auth.form.passwordPlaceholder')}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="auth-input"
              required
              disabled={loading}
              name="new-password"
              id="new-password"
              autoComplete="new-password"
            />
          </div>

          {/* Confirm Password input */}
          <div>
            <input
              type="password"
              placeholder={t('auth.form.passwordConfirmPlaceholder')}
              value={passwordConfirm}
              onChange={(e) => setPasswordConfirm(e.target.value)}
              className="auth-input"
              required
              disabled={loading}
              name="confirm-password"
              id="confirm-password"
              autoComplete="new-password"
            />
          </div>

          {/* Sign Up button */}
          <button type="submit" className="auth-button" disabled={loading}>
            {loading ? t('auth.form.signupButtonLoading') : t('auth.form.signupButton')}
          </button>
        </form>
        <p
          className={['auth-message', !error ? 'auth-message--empty' : '', 'auth-message--error']
            .filter(Boolean)
            .join(' ')}
          aria-hidden={!error}
        >
          {error}
        </p>

        {/* Login link */}
        <div className="auth-footer">
          <p>
            {t('auth.link.alreadyHaveAccountPrefix')}{' '}
            <Link to="/login" className="auth-link">
              {t('auth.link.login')}
            </Link>
          </p>
        </div>
      </div>
      {/* Hidden iframe for password manager (削除) */}
      {/* <iframe name="signup-dummy-frame" id="signup-dummy-frame" src="/empty.html" style={{ display: 'none' }}></iframe> */}
    </div>
  );
}
