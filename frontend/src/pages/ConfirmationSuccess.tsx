import React, { useEffect } from 'react';
import { Link } from 'react-router-dom';
import { BrandWordmark } from '@/components/BrandWordmark';
import { useI18n } from '@/context/useI18n';

const ConfirmationSuccess: React.FC = () => {
  const { t } = useI18n();

  useEffect(() => {
    if (typeof window !== 'undefined' && 'electron' in window) {
      const electron = window.electron;
      if (electron?.auth?.confirmationComplete) {
        void electron.auth.confirmationComplete();
      }
    }
  }, []);

  return (
    <div className="auth-container">
      <div className="app-drag-handle"></div>
      <div className="auth-form">
        <BrandWordmark className="brand-wordmark--auth" />
        <h1>{t('auth.confirmationSuccess.title')}</h1>
        <p>{t('auth.confirmationSuccess.body')}</p>
        <Link to="/login" className="auth-link">
          {t('auth.confirmationSuccess.proceedToLogin')}
        </Link>
      </div>
    </div>
  );
};

export default ConfirmationSuccess;
