import React, { useEffect, useState } from 'react';
import { Link, useLocation } from 'react-router-dom';
import { useAuth } from '../hooks/useAuth';
import { supabase } from '../lib/supabase';
import { useI18n } from '@/context/useI18n';
import { BrandWordmark } from '@/components/BrandWordmark';
import { buildDesktopBrowserAuthUrl } from '@/lib/desktopBrowserAuthUrl';
import { completeDesktopAuthReturn, getDesktopAuthReturnParams } from '@/lib/desktopAuthReturn';

// メッセージのタイプを定義
type MessageType = 'success' | 'error' | null;

const Login: React.FC = () => {
  const { t } = useI18n();
  const [email, setEmail] = useState<string>('');
  const [password, setPassword] = useState<string>('');
  const [message, setMessage] = useState<string>('');
  const [messageType, setMessageType] = useState<MessageType>(null);
  const [isLoading, setIsLoading] = useState<boolean>(false);
  const [desktopReturnUrl, setDesktopReturnUrl] = useState<string | null>(null);
  const [desktopReturnCompleted, setDesktopReturnCompleted] = useState<boolean>(false);
  // null 以外 = 引き渡しの確認待ち（そのアカウントのメールアドレス）
  const [desktopHandoffEmail, setDesktopHandoffEmail] = useState<string | null>(null);
  const { signIn } = useAuth();
  const location = useLocation();

  // メッセージのクラス名を取得
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

  const isElectron = typeof window !== 'undefined' && Boolean(window.electron?.ipcRenderer);

  const openBrowserAuth = (route: 'login' | 'signup' | 'forgot-password') => {
    try {
      const openWithParams = async (): Promise<void> => {
        if (route === 'forgot-password') {
          const url = buildDesktopBrowserAuthUrl(route, null);
          const ipcRenderer =
            typeof window !== 'undefined' ? window.electron?.ipcRenderer : undefined;
          if (ipcRenderer?.send) {
            ipcRenderer.send('open-external-url', url);
            return;
          }
          window.open(url, '_blank');
          return;
        }

        const attempt = await window.electron?.auth?.startBrowserLogin?.(route);
        if (!attempt || attempt.ok !== true) {
          const rawErr = attempt?.error ? String(attempt.error) : '';
          const isPortInUse =
            rawErr.includes('EADDRINUSE') ||
            rawErr.toLowerCase().includes('address already in use');
          setMessageType('error');
          setMessage(isPortInUse ? t('auth.error.loopbackPortInUse') : t('auth.error.generic'));
          console.error('startBrowserLogin failed:', rawErr || '(unknown)');
          try {
            window.alert(isPortInUse ? t('auth.error.loopbackPortInUse') : t('auth.error.generic'));
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
    } catch (error) {
      const msg = error instanceof Error ? error.message : String(error);
      setMessageType('error');
      console.error('openBrowserAuth failed:', msg);
      setMessage(t('auth.error.generic'));
      try {
        window.alert(t('auth.error.generic'));
      } catch {
        // no-op
      }
    }
  };

  // Browser: desktop=1 で、すでにログイン済みの場合。URL を開いただけでセッションを引き渡すと
  // ローカルの別プロセスに乗っ取られるため、利用者が確認して続けるまで発行しない。
  useEffect(() => {
    if (isElectron) return;
    const run = async () => {
      const desktopReturnParams = getDesktopAuthReturnParams(location.search || '');
      if (!desktopReturnParams.isDesktopReturn) return;

      const {
        data: { session },
      } = await supabase.auth.getSession();
      if (!session) {
        return;
      }

      // loopback callback → Webへ戻された場合は「完了画面」で止める（ここで再度 issue/exchange を走らせない）
      if (desktopReturnParams.isDesktopReturnCompleted) {
        setDesktopReturnCompleted(true);
        setMessageType('success');
        setMessage(t('auth.message.loginSuccessContinue'));
        return;
      }

      if (!desktopReturnParams.attemptId || !desktopReturnParams.codeChallenge) return;
      setDesktopHandoffEmail(session.user?.email || '');
    };
    run();
  }, [isElectron, location.search, t]);

  const handleDesktopHandoff = async (): Promise<void> => {
    setIsLoading(true);
    try {
      const {
        data: { session },
      } = await supabase.auth.getSession();
      const returnResult = await completeDesktopAuthReturn(
        getDesktopAuthReturnParams(location.search || ''),
        session
      );
      if (!returnResult.ok) {
        throw new Error(returnResult.error);
      }
      if (returnResult.returnUrl) {
        setDesktopReturnUrl(returnResult.returnUrl);
        setMessageType('success');
        setMessage(t('auth.message.loginSuccessOpening'));
        window.location.assign(returnResult.returnUrl);
      }
    } catch (error) {
      setMessageType('error');
      setMessage(t('auth.error.desktopReturnFailed'));
      console.error('Desktop return failed:', error);
    } finally {
      setIsLoading(false);
    }
  };

  const handleSignIn = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsLoading(true);
    setMessage('');

    // Custom email validation (specific checks only)
    if (email && !email.includes('@')) {
      // Check for missing '@' only if email is not empty
      setMessageType('error');
      setMessage(t('auth.error.emailNeedsAt'));
      setIsLoading(false);
      return;
    } else if (email && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
      // Basic format check only if email is not empty
      setMessageType('error');
      setMessage(t('auth.error.emailInvalid'));
      setIsLoading(false);
      return;
    }

    try {
      // 実際のフォーム要素を取得 (削除)
      // const formElement = e.target as HTMLFormElement;

      // 通常のログイン処理を実行
      const { error } = await signIn(email, password);

      if (error) {
        setMessageType('error');
        if (error.message.includes('user not found')) {
          setMessage(t('auth.error.loginInvalid'));
        } else if (error.message.includes('Invalid login credentials')) {
          setMessage(t('auth.error.loginInvalid'));
        } else if (error.message.includes('invalid email')) {
          setMessage(t('auth.error.loginInvalid'));
        } else if (error.message.includes('too many requests')) {
          setMessage(t('auth.error.tooManyAttempts'));
        } else {
          console.error('Login error:', error);
          setMessage(t('auth.error.generic'));
        }
        setIsLoading(false);
      } else {
        setMessageType('success');
        setMessage(t('auth.message.loginSuccessContinue'));
        setPassword(''); // セキュリティ: ブラウザ上に平文パスワードを残さない

        // ログイン後は Desktop アプリへ復帰（deep link）できるようにURLを生成する。
        // - desktop=1 の場合は直ちに遷移を試す
        // - ブラウザにブロックされた場合に備えて「Open Desktop App」ボタンも出す
        try {
          const {
            data: { session },
          } = await supabase.auth.getSession();
          const desktopReturnParams = getDesktopAuthReturnParams(location.search || '');
          const returnResult = await completeDesktopAuthReturn(desktopReturnParams, session);
          if (!returnResult.ok) {
            throw new Error(returnResult.error);
          }
          if (returnResult.returnUrl) {
            setDesktopReturnUrl(returnResult.returnUrl);
            if (desktopReturnParams.isDesktopReturn) {
              setMessage(t('auth.message.loginSuccessOpening'));
              window.location.assign(returnResult.returnUrl);
            }
          }
        } catch (e) {
          const msg = e instanceof Error ? e.message : String(e);
          setMessageType('error');
          console.error('Desktop return failed:', msg);
          setMessage(t('auth.error.desktopReturnFailed'));
          setIsLoading(false);
          return;
        }

        // ブラウザではアプリ本体（/history等）へ遷移しない（認証ポータル用途に限定）
        setIsLoading(false);
      }
    } catch (error: unknown) {
      setMessageType('error');
      console.error('Login unexpected error:', error);
      setMessage(t('auth.error.generic'));
      setIsLoading(false);
    }
  };

  const handleBrowserSignOut = async (): Promise<void> => {
    setIsLoading(true);
    try {
      const { error } = await supabase.auth.signOut();
      if (error) {
        throw error;
      }
      setDesktopReturnUrl(null);
      setDesktopHandoffEmail(null);
      setMessageType(null);
      setMessage('');
      setEmail('');
      setPassword('');
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      setMessageType('error');
      console.error('Sign out failed:', msg);
      setMessage(t('auth.error.signOutFailed'));
    } finally {
      setIsLoading(false);
    }
  };

  // Electron では、ブラウザ（Chrome等）のパスワードマネージャーを利用できるよう
  // 認証UIをアプリ内に持たず、外部ブラウザでログインする。
  if (isElectron) {
    return (
      <div className="auth-container">
        <div className="app-drag-handle"></div>
        <div className="auth-form auth-form--fixed-height">
          <Link className="auth-link" to="/history">
            {t('auth.link.backToApp')}
          </Link>
          <BrandWordmark className="brand-wordmark--auth" />
          <h2>{t('auth.login.desktopTitle')}</h2>
          <p>
            {t('auth.login.electronDescription')
              .split('\n')
              .map((line, idx) => (
                <React.Fragment key={`${line}-${idx}`}>
                  {line}
                  <br />
                </React.Fragment>
              ))}
          </p>
          <div className="auth-actions">
            <button type="button" className="auth-button" onClick={() => openBrowserAuth('login')}>
              {t('auth.login.openBrowserLogin')}
            </button>
            <button type="button" className="auth-button" onClick={() => openBrowserAuth('signup')}>
              {t('auth.login.openBrowserSignup')}
            </button>
            <button
              type="button"
              className="auth-button"
              onClick={() => openBrowserAuth('forgot-password')}
            >
              {t('auth.login.openBrowserReset')}
            </button>
          </div>
          <p
            className={[
              'auth-message',
              !message ? 'auth-message--empty' : '',
              getMessageClassName(messageType),
            ]
              .filter(Boolean)
              .join(' ')}
            aria-hidden={!message}
          >
            {message}
          </p>
        </div>
      </div>
    );
  }

  // Browser（認証ポータル）: ログイン済みなら入力フォームを隠して「Desktopへ戻る」導線に寄せる
  if (desktopReturnCompleted) {
    return (
      <div className="auth-container">
        <div className="app-drag-handle"></div>
        <div className="auth-form">
          <BrandWordmark className="brand-wordmark--auth" />
          <h2>{t('auth.login.completedTitle')}</h2>
          <p>{message || t('auth.message.loginSuccessContinue')}</p>
          <div className="auth-actions" style={{ marginTop: '14px' }}>
            <button
              type="button"
              className="auth-button"
              onClick={handleBrowserSignOut}
              disabled={isLoading}
            >
              {t('auth.button.useAnotherAccount')}
            </button>
          </div>
          <p>{t('auth.hint.closeTabAfterReturning')}</p>
        </div>
      </div>
    );
  }

  if (desktopReturnUrl) {
    return (
      <div className="auth-container">
        <div className="app-drag-handle"></div>
        <div className="auth-form">
          <BrandWordmark className="brand-wordmark--auth" />
          <h2>{t('auth.login.title')}</h2>
          <p>{message || t('auth.message.loginSuccessContinue')}</p>
          <div className="auth-actions" style={{ marginTop: '14px' }}>
            <button
              type="button"
              className="auth-button"
              onClick={() => window.location.assign(desktopReturnUrl)}
              disabled={isLoading}
            >
              {t('auth.button.openDesktopApp')}
            </button>
            <button
              type="button"
              className="auth-button"
              onClick={handleBrowserSignOut}
              disabled={isLoading}
            >
              {t('auth.button.useAnotherAccount')}
            </button>
          </div>
          <p>{t('auth.hint.closeTabAfterReturning')}</p>
        </div>
      </div>
    );
  }

  if (desktopHandoffEmail !== null) {
    return (
      <div className="auth-container">
        <div className="app-drag-handle"></div>
        <div className="auth-form">
          <BrandWordmark className="brand-wordmark--auth" />
          <h2>{t('auth.desktopHandoff.title')}</h2>
          <p>{t('auth.desktopHandoff.body', { email: desktopHandoffEmail })}</p>
          <div className="auth-actions" style={{ marginTop: '14px' }}>
            <button
              type="button"
              className="auth-button"
              onClick={handleDesktopHandoff}
              disabled={isLoading}
            >
              {t('auth.desktopHandoff.continue')}
            </button>
            <button
              type="button"
              className="auth-button"
              onClick={handleBrowserSignOut}
              disabled={isLoading}
            >
              {t('auth.button.useAnotherAccount')}
            </button>
          </div>
          <p>{t('auth.desktopHandoff.hint')}</p>
          <p
            className={[
              'auth-message',
              !message ? 'auth-message--empty' : '',
              getMessageClassName(messageType),
            ]
              .filter(Boolean)
              .join(' ')}
            aria-hidden={!message}
          >
            {message}
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="auth-container">
      <div className="app-drag-handle"></div>
      <div className="auth-form auth-form--fixed-height">
        <BrandWordmark className="brand-wordmark--auth" />
        <h2>{t('auth.login.title')}</h2>
        <form onSubmit={handleSignIn} noValidate>
          <div>
            <input
              type="email"
              placeholder={t('auth.form.emailPlaceholder')}
              value={email}
              onChange={(e) => {
                setEmail(e.target.value);
              }}
              required
              className="auth-input"
              name="email"
              id="email"
              autoComplete="username email"
            />
          </div>
          <div>
            <input
              type="password"
              placeholder={t('auth.form.passwordPlaceholder')}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              className="auth-input"
              name="password"
              id="password"
              autoComplete="current-password"
            />
          </div>
          <button type="submit" disabled={isLoading} className="auth-button">
            {isLoading ? t('auth.form.loginButtonLoading') : t('auth.form.loginButton')}
          </button>
          <p
            className={[
              'auth-message',
              !message ? 'auth-message--empty' : '',
              getMessageClassName(messageType),
            ]
              .filter(Boolean)
              .join(' ')}
            aria-hidden={!message}
          >
            {message}
          </p>
        </form>
        <div className="auth-footer">
          <p>
            <Link to="/forgot-password" className="auth-link">
              {t('auth.link.forgotPassword')}
            </Link>
          </p>
          <p>
            {t('auth.link.noAccountPrefix')}{' '}
            <Link to="/signup" className="auth-link">
              {t('auth.link.signUp')}
            </Link>
          </p>
        </div>
      </div>
    </div>
  );
};

export default Login;
