import { Link, useLocation } from 'react-router-dom';
import { useAuth } from '@/hooks/useAuth';
import { useI18n } from '@/context/useI18n';
import type { MessageKey } from '@/i18n/types';
import { PANTARAY_ACCOUNT_LOGIN_ENABLED } from '../../electron/src/auth/accountLoginFeature';
import { useAiConnectionController } from '@/pages/settings/useAiConnectionController';

export function AiConnectionNotice() {
  const { authStatus } = useAuth();
  const { state, loadError } = useAiConnectionController();
  const { t } = useI18n();
  const location = useLocation();
  if (
    location.pathname === '/settings' &&
    new URLSearchParams(location.search).get('section') === 'ai_connection'
  ) {
    return null;
  }

  let message: MessageKey;
  const expired = PANTARAY_ACCOUNT_LOGIN_ENABLED && authStatus === 'expired';
  if (expired) {
    message = 'layout.aiConnection.expired';
  } else if (loadError || (state && !state.runtime.ok)) {
    message = 'layout.aiConnection.unavailable';
  } else if (
    state?.runtime.ok &&
    state.runtime.status.configured &&
    state.runtime.status.llmRoute === 'unconfigured'
  ) {
    message = 'layout.aiConnection.unconfigured';
  } else {
    return null;
  }

  return (
    <div className="app-connection-notice" role="status">
      <p>{t(message)}</p>
      <Link to={expired ? '/login' : '/settings?section=ai_connection'}>
        {t(expired ? 'layout.aiConnection.login' : 'layout.aiConnection.configure')}
      </Link>
    </div>
  );
}
