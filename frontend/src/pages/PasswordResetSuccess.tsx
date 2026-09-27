import React, { useEffect } from 'react';
import { Link } from 'react-router-dom';
import { BrandWordmark } from '@/components/BrandWordmark';
import { useI18n } from '@/context/useI18n';

const PasswordResetSuccess: React.FC = () => {
  const { t } = useI18n();

  useEffect(() => {
    if (typeof window === 'undefined') return;
    const electron = window.electron;
    if (electron?.auth?.confirmationComplete) {
      void electron.auth.confirmationComplete();
    }
  }, []);

  return (
    <div className="auth-container">
      <div className="app-drag-handle"></div>
      <div className="auth-form">
        <BrandWordmark className="brand-wordmark--auth" />
        <h1>{t('auth.passwordResetSuccess.title')}</h1>
        <p>{t('auth.passwordResetSuccess.body')}</p>
        <Link to="/login" className="auth-link">
          {t('auth.passwordResetSuccess.returnToLogin')}
        </Link>
      </div>
    </div>
  );
};

export default PasswordResetSuccess;
