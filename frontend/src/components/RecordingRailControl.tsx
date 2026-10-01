import { Settings2 } from 'lucide-react';
import { useRef, useState, type RefObject } from 'react';
import { useNavigate } from 'react-router-dom';

import { useI18n } from '@/context/useI18n';
import { useDismissablePopover } from '@/pages/settings/useDismissablePopover';
import { useScreenshotCaptureStatus } from '@/pages/settings/useScreenshotCaptureStatus';

const POPOVER_ID = 'app-recording-popover';

type CaptureStatus = ReturnType<typeof useScreenshotCaptureStatus>;

/** The rail's recording light, and the popover that holds the recording controls. */
export function RecordingRailControl() {
  const { t } = useI18n();
  const capture = useScreenshotCaptureStatus();
  const triggerRef = useRef<HTMLButtonElement>(null);
  const [isOpen, setIsOpen] = useState(false);

  const label = capture.captureStatusUnavailable
    ? t('settings.screenshotCapture.unavailable')
    : t('layout.recordingStatus', {
        status:
          capture.isCapturingScreenshots === null
            ? t('settings.loadingStatus')
            : t(capture.isCapturingScreenshots ? 'common.on' : 'common.off'),
      });

  return (
    <div className="app-recording">
      <button
        ref={triggerRef}
        type="button"
        className="app-rail-item"
        aria-label={label}
        title={label}
        aria-haspopup="dialog"
        aria-expanded={isOpen}
        aria-controls={isOpen ? POPOVER_ID : undefined}
        onClick={() => setIsOpen((current) => !current)}
      >
        <span
          className={[
            'app-recording-light',
            capture.isCapturingScreenshots ? 'app-recording-light--on' : null,
          ]
            .filter(Boolean)
            .join(' ')}
          aria-hidden="true"
        />
      </button>
      {isOpen ? (
        <RecordingPopover
          capture={capture}
          triggerRef={triggerRef}
          onDismiss={() => setIsOpen(false)}
        />
      ) : null}
    </div>
  );
}

function RecordingPopover({
  capture,
  triggerRef,
  onDismiss,
}: {
  capture: CaptureStatus;
  triggerRef: RefObject<HTMLButtonElement>;
  onDismiss: () => void;
}) {
  const { t } = useI18n();
  const navigate = useNavigate();
  const { popoverRef } = useDismissablePopover({ isOpen: true, triggerRef, onDismiss });
  const {
    isCapturingScreenshots,
    captureStatusUnavailable,
    isProcessing,
    isScreenshotCaptureAvailable,
    setScreenshotsEnabled,
  } = capture;

  const isToggleDisabled =
    isProcessing || (!isCapturingScreenshots && !isScreenshotCaptureAvailable);

  return (
    <div
      ref={popoverRef}
      id={POPOVER_ID}
      className="app-recording-popover"
      role="dialog"
      aria-label={t('settings.screenshotCapture.title')}
      tabIndex={-1}
    >
      <div className="app-recording-row">
        <div className="app-recording-title">{t('settings.screenshotCapture.title')}</div>
        {/* role="switch" cannot express an unknown state, so the switch appears only
            once the status IPC has answered; the placeholder holds the row height. */}
        {isCapturingScreenshots === null ? (
          <span className="settings-toggle settings-toggle--compact" aria-hidden="true" />
        ) : (
          <button
            type="button"
            role="switch"
            aria-checked={isCapturingScreenshots}
            aria-label={t('settings.screenshotCapture.screenshotsLabel')}
            className={[
              'settings-toggle',
              'settings-toggle--compact',
              isCapturingScreenshots ? 'settings-toggle--on' : null,
            ]
              .filter(Boolean)
              .join(' ')}
            disabled={isToggleDisabled}
            onClick={() => void setScreenshotsEnabled(!isCapturingScreenshots)}
          >
            <span className="settings-toggle-thumb" />
            <span className="settings-toggle-label">
              {isCapturingScreenshots ? t('common.on') : t('common.off')}
            </span>
          </button>
        )}
      </div>
      <div className="app-recording-status" role={captureStatusUnavailable ? 'alert' : undefined}>
        {captureStatusUnavailable
          ? t('settings.screenshotCapture.unavailable')
          : isCapturingScreenshots === null
            ? t('settings.loadingStatus')
            : isCapturingScreenshots
              ? t('common.active')
              : `${t('common.paused')}・${t('settings.screenshotCapture.pausedSuggestions')}`}
      </div>

      <button
        type="button"
        className="app-recording-settings-link"
        onClick={() => {
          onDismiss();
          navigate('/settings?section=screenshots');
        }}
      >
        <Settings2 size={14} aria-hidden="true" />
        <span>{t('settings.recordingFilter.openSettings')}</span>
      </button>
    </div>
  );
}
