export type CaptureStatusKind =
  | 'capturing'
  | 'degraded'
  | 'waiting'
  | 'paused'
  | 'blocked_by_app'
  | 'blocked_by_url'
  | 'blocked_by_ide'
  | 'editing_paused'
  | 'permission_required'
  | 'disconnected'
  | 'unavailable'
  | 'checking';

export type CaptureStatusLastResult = 'uploaded' | 'skipped' | 'failed' | null;

export type CaptureStatusSnapshot = {
  kind: CaptureStatusKind;
  screenshotsEnabled: boolean;
  activeWindow: {
    appName: string | null;
    title: string | null;
  };
  browserUrl: {
    appName: string | null;
    host: string | null;
    path: string | null;
    error: string | null;
  } | null;
  lastCaptureAt: string | null;
  lastCaptureResult: CaptureStatusLastResult;
  reasonLabel: string;
};
