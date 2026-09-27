import React, { useState } from 'react';
import { Link } from 'react-router-dom';
import { useAuth } from '../hooks/useAuth';
import { useI18n } from '@/context/useI18n';
import { BrandWordmark } from '@/components/BrandWordmark';
import { buildDesktopBrowserAuthUrl } from '@/lib/desktopBrowserAuthUrl';

// Define message types
type MessageType = 'success' | 'error' | null;

const ForgotPassword: React.FC = () => {
  const { t } = useI18n();
  const [email, setEmail] = useState<string>('');
  const [message, setMessage] = useState<string>('');
  const [messageType, setMessageType] = useState<MessageType>(null);
  const [isLoading, setIsLoading] = useState<boolean>(false);
  const { resetPassword } = useAuth();
  const isElectron = typeof window !== 'undefined' && Boolean(window.electron?.ipcRenderer);

  const openBrowserAuth = (route: 'login' | 'forgot-password') => {
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

  if (isElectron) {
    return (
      <div className="auth-container">
        <div className="app-drag-handle"></div>
        <div className="auth-form">
          <BrandWordmark className="brand-wordmark--auth" />
          <h2>{t('auth.forgot.title')}</h2>
          <p>{t('auth.forgot.electronDescription')}</p>
          <button
            type="button"
            className="auth-button"
            onClick={() => openBrowserAuth('forgot-password')}
          >
            {t('auth.forgot.openBrowserReset')}
          </button>
          {message && (
            <p className={`auth-message ${getMessageClassName(messageType)}`}>{message}</p>
          )}
          <p>
            <button type="button" className="auth-link" onClick={() => openBrowserAuth('login')}>
              {t('auth.forgot.backToLoginBrowser')}
            </button>
          </p>
        </div>
      </div>
    );
  }

  const handleResetPassword = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsLoading(true);
    setMessage('');

    // Custom email validation
    if (!email) {
      setMessageType('error');
      setMessage(t('auth.error.emailRequired'));
      setIsLoading(false);
      return;
    } else if (!email.includes('@')) {
      setMessageType('error');
      setMessage(t('auth.error.emailNeedsAt'));
      setIsLoading(false);
      return;
    } else if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
      setMessageType('error');
      setMessage(t('auth.error.emailInvalid'));
      setIsLoading(false);
      return;
    }

    try {
      const { error } = await resetPassword(email);

      if (error) {
        setMessageType('error');
        if (error.message.toLowerCase().includes('user not found')) {
          setMessage(t('auth.error.resetNoAccount'));
        } else {
          console.error('Reset password error:', error);
          setMessage(t('auth.error.generic'));
        }
      } else {
        setMessageType('success');
        setMessage(t('auth.message.resetSent'));
      }
    } catch (error: unknown) {
      setMessageType('error');
      console.error('Reset password unexpected error:', error);
      setMessage(t('auth.error.generic'));
    } finally {
      setIsLoading(false);
    }
  };

  // Get message class name
  function getMessageClassName(type: MessageType): string {
    switch (type) {
      case 'success':
        return 'auth-message--success';
      case 'error':
        return 'auth-message--error';
      default:
        return '';
    }
  }

  return (
    <div className="auth-container">
      <div className="app-drag-handle"></div>
      <div className="auth-form">
        <BrandWordmark className="brand-wordmark--auth" />
        <h2>{t('auth.forgot.title')}</h2>
        <form onSubmit={handleResetPassword} noValidate>
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
              autoComplete="email"
            />
          </div>
          <button type="submit" disabled={isLoading} className="auth-button">
            {isLoading ? t('auth.form.resetSendButtonLoading') : t('auth.form.resetSendButton')}
          </button>
          {message && (
            <p className={`auth-message ${getMessageClassName(messageType)}`}>{message}</p>
          )}
        </form>
        <p>
          <Link to="/login" className="auth-link">
            {t('auth.link.backToLogin')}
          </Link>
        </p>
      </div>
    </div>
  );
};

export default ForgotPassword;
