import { useEffect, useState } from 'react';
import { RefreshCw } from 'lucide-react';
import type { UpdateReadyNotice as Notice } from '../../electron/src/ipc/context';
import { useI18n } from '@/context/useI18n';

/** Main-window button for a downloaded update. It stays until the update is installed. */
export function UpdateReadyNotice() {
  const { t } = useI18n();
  const [notice, setNotice] = useState<Notice | null>(null);

  useEffect(() => {
    const update = window.electron?.update;
    if (!update) return;
    let active = true;
    const read = () => {
      void update.getReadyNotice().then((next) => {
        if (active) setNotice(next);
      });
    };
    const unsubscribe = update.onReadyNoticeChanged(read);
    read();
    return () => {
      active = false;
      unsubscribe();
    };
  }, []);

  // The live region stays mounted so the button's appearance is announced.
  return (
    <div className="app-update-notice-region" role="status" aria-live="polite">
      {notice && (
        <button
          type="button"
          className="app-update-button"
          title={
            notice.version
              ? t('layout.updateReady.hint', { version: notice.version })
              : t('layout.updateReady.hintWithoutVersion')
          }
          onClick={() => void window.electron?.update?.restartToUpdate()}
        >
          <RefreshCw size={13} aria-hidden="true" />
          {notice.version
            ? t('layout.updateReady.button', { version: notice.version })
            : t('layout.updateReady.buttonWithoutVersion')}
        </button>
      )}
    </div>
  );
}
