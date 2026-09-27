import React from 'react';
import { Link, Navigate } from 'react-router-dom';
import { BrandWordmark } from '@/components/BrandWordmark';
import { useI18n } from '@/context/useI18n';
import { PANTARAY_ACCOUNT_LOGIN_ENABLED } from '../../electron/src/auth/accountLoginFeature';

/**
 * ブラウザ（Web）からのアクセスを制限するための案内ページ。
 *
 * 目的:
 * - `history` や `settings` 等の「デスクトップアプリ専用機能」を
 *   ブラウザで閲覧できてしまう状態を防止する。
 *
 * 方針:
 * - ログイン停止中は共通の停止案内へ送る。
 * - ログイン有効時は認証ページ以外を本ページで案内する。
 */
const DesktopAppOnlyPage: React.FC = () => {
  const { t } = useI18n();

  if (!PANTARAY_ACCOUNT_LOGIN_ENABLED) return <Navigate to="/login" replace />;

  return (
    <div className="auth-container">
      <div className="auth-form">
        <BrandWordmark className="brand-wordmark--auth" />
        <h2>{t('desktopAppOnly.title')}</h2>
        <p>{t('desktopAppOnly.body')}</p>
        <div className="auth-actions">
          <Link to="/login" className="auth-button">
            {t('desktopAppOnly.goToLogin')}
          </Link>
        </div>
      </div>
    </div>
  );
};

export default DesktopAppOnlyPage;
