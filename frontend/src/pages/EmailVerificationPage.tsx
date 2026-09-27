import React from 'react';
import { Link } from 'react-router-dom';
import { BrandWordmark } from '@/components/BrandWordmark';
import { useI18n } from '@/context/useI18n';

const EmailVerificationPage: React.FC = () => {
  const { t } = useI18n();

  return (
    <div className="auth-container">
      <div className="app-drag-handle"></div>
      <div className="auth-form">
        <BrandWordmark className="brand-wordmark--auth" />
        <h1>{t('auth.emailVerification.title')}</h1>
        <p>{t('auth.emailVerification.body')}</p>
        <p>{t('auth.emailVerification.hint')}</p>
        <Link to="/login" className="auth-link">
          {t('auth.emailVerification.returnToLogin')}
        </Link>
      </div>
    </div>
  );
};

export default EmailVerificationPage;
