import { useEffect, useState } from 'react';
import type { UpdateReadyNotice as Notice } from '../../electron/src/ipc/context';
import { useI18n } from '@/context/useI18n';

/** Main-window chip for a downloaded update. Main owns the state, including "later". */
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

  const dismiss = () => {
    setNotice(null);
    void window.electron?.update?.dismissReadyNotice();
  };

  // The live region stays mounted so the chip's appearance is announced.
  return (
    <div className="app-update-notice-region" role="status" aria-live="polite">
      {notice && (
        <div className="app-update-notice">
          <p>
            {notice.version
              ? t('layout.updateReady.message', { version: notice.version })
              : t('layout.updateReady.messageWithoutVersion')}
          </p>
          <button
            type="button"
            className="app-update-notice-restart"
            onClick={() => void window.electron?.update?.restartToUpdate()}
          >
            {t('layout.updateReady.restart')}
          </button>
          <button type="button" className="app-update-notice-later" onClick={dismiss}>
            {t('layout.updateReady.later')}
          </button>
        </div>
      )}
    </div>
  );
}
