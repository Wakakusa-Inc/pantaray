import React, { useState, useRef, useEffect } from 'react';
import { UserRound } from 'lucide-react';
import { Link, Outlet, useLocation, useNavigate } from 'react-router-dom';
import { useAuth } from '@/hooks/useAuth';
import { useI18n } from '@/context/useI18n';
import { RecordingIntroDialog } from './RecordingIntroDialog';
import { AiConnectionNotice } from './AiConnectionNotice';
import { LocalOwnerBoundary } from './LocalOwnerBoundary';
import { PANTARAY_ACCOUNT_LOGIN_ENABLED } from '../../electron/src/auth/accountLoginFeature';
import './Layout.css';

/**
 * アプリ全体で共通利用するレイアウト。
 * シンプルなヘッダーナビゲーションと中央寄せのコンテンツ領域で構成する。
 */
const Layout: React.FC = () => {
  const { user, signOut, authStatus } = useAuth();
  const needsLogin = authStatus === 'expired';
  const hasAccount = authStatus === 'authenticated' || needsLogin;
  const [isDropdownOpen, setIsDropdownOpen] = useState(false);
  const menuButtonRef = useRef<HTMLButtonElement>(null);
  const dropdownRef = useRef<HTMLDivElement>(null);
  const { t } = useI18n();
  const navigate = useNavigate();
  const location = useLocation();

  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target as Node)) {
        setIsDropdownOpen(false);
      }
    };

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setIsDropdownOpen(false);
        menuButtonRef.current?.focus();
      }
    };

    if (isDropdownOpen) {
      document.addEventListener('keydown', handleKeyDown);
      document.addEventListener('mousedown', handleClickOutside);
    }

    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
      document.removeEventListener('keydown', handleKeyDown);
    };
  }, [isDropdownOpen]);

  const handleLogout = async () => {
    setIsDropdownOpen(false);
    const { error } = await signOut();
    if (error) {
      console.error('Error during logout:', error);
    }
  };

  const getUserInitials = (email: string | undefined): string => {
    if (!email) return 'U';
    const parts = email.split('@')[0].split('.');
    if (parts.length >= 2) {
      return (parts[0][0] + parts[1][0]).toUpperCase();
    }
    return email[0].toUpperCase();
  };

  const isHistoryActive = location.pathname === '/history';
  const isWorkspaceActive = location.pathname === '/workspace';
  const isSettingsActive = location.pathname === '/settings';

  return (
    <div className="app-shell">
      <header className="app-header">
        <div className="app-header-inner">
          <div className="app-header-spacer" />
          <nav className="app-header-nav">
            <button
              type="button"
              onClick={() => navigate('/history')}
              className={['app-nav-link', isHistoryActive ? 'app-nav-link--active' : null]
                .filter(Boolean)
                .join(' ')}
              aria-current={isHistoryActive ? 'page' : undefined}
            >
              {t('nav.history')}
            </button>
            <button
              type="button"
              onClick={() => navigate('/workspace')}
              className={['app-nav-link', isWorkspaceActive ? 'app-nav-link--active' : null]
                .filter(Boolean)
                .join(' ')}
              aria-current={isWorkspaceActive ? 'page' : undefined}
            >
              {t('settings.workspace.title')}
            </button>
            <button
              type="button"
              onClick={() => navigate('/settings')}
              className={['app-nav-link', isSettingsActive ? 'app-nav-link--active' : null]
                .filter(Boolean)
                .join(' ')}
              aria-current={isSettingsActive ? 'page' : undefined}
            >
              {t('nav.settings')}
            </button>
          </nav>
          {PANTARAY_ACCOUNT_LOGIN_ENABLED && (
            <div className="app-header-user" ref={dropdownRef}>
              <button
                type="button"
                ref={menuButtonRef}
                aria-expanded={isDropdownOpen}
                aria-controls="app-user-dropdown"
                className="app-user-button"
                onClick={() => setIsDropdownOpen(!isDropdownOpen)}
                aria-label={t('layout.userMenuAriaLabel')}
              >
                {user ? getUserInitials(user.email) : <UserRound size={18} aria-hidden="true" />}
              </button>
              {isDropdownOpen && (
                <div className="app-user-dropdown" id="app-user-dropdown">
                  {user?.email && <div className="app-user-dropdown-email">{user.email}</div>}
                  {needsLogin && (
                    <p className="app-user-dropdown-email" role="status">
                      {t('layout.sessionExpired')}
                    </p>
                  )}
                  {!user && (
                    <Link
                      className="app-user-dropdown-item"
                      to="/login"
                      onClick={() => setIsDropdownOpen(false)}
                    >
                      {t(needsLogin ? 'menu.reauthenticate' : 'menu.login')}
                    </Link>
                  )}
                  {hasAccount && (
                    <button className="app-user-dropdown-item" onClick={handleLogout}>
                      {t('menu.logout')}
                    </button>
                  )}
                </div>
              )}
            </div>
          )}
        </div>
      </header>

      {/* Recording belongs to the local owner; without one there is nothing to ask for. */}
      <LocalOwnerBoundary fallback={null}>
        <RecordingIntroDialog />
      </LocalOwnerBoundary>

      <main className="app-main">
        <div className="app-surface">
          <AiConnectionNotice />
          <Outlet />
        </div>
      </main>
    </div>
  );
};

export default Layout;
