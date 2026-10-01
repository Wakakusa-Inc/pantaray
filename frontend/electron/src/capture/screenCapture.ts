/**
 * Answering one `capture_screen` request from the Action runtime.
 *
 * The runtime cannot see the screen and cannot decide whether it may: the macOS
 * Screen Recording permission and the user's recording filter both live here. It
 * names an app, this module finds that app's window, decides, and the answer goes
 * back over the local backend.
 *
 * Only the one window is captured: the app's frontmost window on screen, whether or
 * not other windows cover it. What the window shows is judged before it is captured
 * (`privacy/windowCapturePolicy.ts`), and judged again right after: a browser tab can
 * change between the two, and an image is kept only when both judgements pass. The
 * gates, in the order they settle:
 *
 * 1. Screen Recording permission. Without it macOS returns windowless pictures,
 *    which look like a successful capture and are not one.
 * 2. Filter editing in progress: while the user is changing the rules, the rules
 *    that would apply are not settled.
 * 3. The named app has a window on screen. A refusal lists the apps that do and that
 *    the filter admits, and nothing else - no excluded app, no window title.
 * 4. The app-level rules, then what the window shows.
 *
 * Design limit: a minimized or hidden window, or one on another desktop, is not on
 * screen and cannot be captured.
 */

import { createHash, randomUUID } from 'crypto';
import path from 'path';

import type { CapturePrivacySettings } from '../privacy/capturePrivacy';
import {
  captureSurface,
  decideAppCapture,
  decideWindowContents,
  type BrowserWindowObservation,
  type CaptureRefusal,
  type WindowBounds,
} from '../privacy/windowCapturePolicy';
import { storedImageAbsolutePath } from '../protocol/imageProtocol';
import { imageStorageDateSegment, isValidImageStoragePath } from '../protocol/imageStoragePath';

export type ScreenCaptureRequest = {
  captureRequestId: string;
  actionId: string;
  processId: string;
  toolRequestId: string;
  appName: string;
};

/** One on-screen window of a regular app, as CoreGraphics lists it. */
export type OnScreenWindow = {
  windowId: number;
  appName: string;
  bundleId: string | null;
  /** Null when macOS does not report one. */
  title: string | null;
  alpha: number;
  bounds: WindowBounds;
};

export type CapturedScreenImage = {
  png: Buffer;
  widthPx: number;
  heightPx: number;
};

export type ScreenCaptureAnswer =
  | {
      status: 'captured';
      storage_path: string;
      mime_type: 'image/png';
      byte_size: number;
      sha256: string;
      width_px: number;
      height_px: number;
      app_name: string;
      captured_at: string;
    }
  | CaptureRefusal;

export type ScreenCaptureDeps = {
  /** `systemPreferences.getMediaAccessStatus('screen')`. */
  readScreenRecordingStatus: () => string;
  getCaptureSettings: () => CapturePrivacySettings;
  isCaptureEditing: () => boolean;
  /** On-screen windows of regular apps, frontmost first. */
  listWindows: () => Promise<OnScreenWindow[]>;
  /** Every window of a running browser, or null when the browser could not be asked. */
  readBrowserWindows: (browser: 'chrome' | 'safari') => Promise<BrowserWindowObservation[] | null>;
  /** That one window's pixels, or null when macOS produced no image of it. */
  captureWindow: (window: OnScreenWindow) => Promise<CapturedScreenImage | null>;
  getCurrentSubjectId: () => string | null;
  localArtifactRoot: () => string;
  writeFileAtomic: (targetPath: string, tempDirectoryPath: string, payload: Buffer) => void;
  now: () => Date;
};

/**
 * Below this, a window is a helper surface (an app's 1x1 placeholder, a status
 * strip) rather than something a user reads.
 */
const MIN_TARGET_WINDOW_POINTS = 50;

/** CoreGraphics and Apple Events report the same frame up to rounding. */
const FRAME_MATCH_TOLERANCE_POINTS = 1;

export async function answerScreenCapture(
  deps: ScreenCaptureDeps,
  appName: string
): Promise<ScreenCaptureAnswer> {
  if (deps.readScreenRecordingStatus() !== 'granted') {
    return { status: 'refused', code: 'SCREEN_RECORDING_PERMISSION_REQUIRED' };
  }
  if (deps.isCaptureEditing()) {
    return { status: 'refused', code: 'CAPTURE_REFUSED_BY_PRIVACY_FILTER', axis: 'editing' };
  }
  const settings = deps.getCaptureSettings();
  const windows = await deps.listWindows();
  const target = frontWindowOf(windows, appName);
  if (target === null) return targetNotFound(settings, windows);

  const before = await judgeWindow(deps, settings, target);
  if (before !== null) return before;
  const captured = await deps.captureWindow(target);
  const after = (await deps.listWindows()).find(
    (window) => window.windowId === target.windowId && isTargetable(window)
  );
  if (captured === null || after === undefined) return targetNotFound(settings, windows);
  // The image exists only in memory until this passes; a refusal here discards it.
  const recheck = await judgeWindow(deps, settings, after);
  if (recheck !== null) return recheck;
  return storeCapture(deps, { captured, appName: target.appName });
}

function frontWindowOf(windows: OnScreenWindow[], appName: string): OnScreenWindow | null {
  const wanted = appName.trim().toLowerCase();
  return (
    windows.find(
      (window) => isTargetable(window) && window.appName.trim().toLowerCase() === wanted
    ) ?? null
  );
}

function isTargetable(window: OnScreenWindow): boolean {
  return (
    window.alpha > 0 &&
    window.bounds.width >= MIN_TARGET_WINDOW_POINTS &&
    window.bounds.height >= MIN_TARGET_WINDOW_POINTS
  );
}

function targetNotFound(
  settings: CapturePrivacySettings,
  windows: OnScreenWindow[]
): CaptureRefusal {
  const available = windows
    .filter((window) => isTargetable(window))
    .filter(
      (window) =>
        decideAppCapture(settings, { name: window.appName, bundleId: window.bundleId }) === null
    )
    .map((window) => window.appName);
  return {
    status: 'refused',
    code: 'CAPTURE_TARGET_NOT_FOUND',
    available_apps: [...new Set(available)],
  };
}

async function judgeWindow(
  deps: ScreenCaptureDeps,
  settings: CapturePrivacySettings,
  window: OnScreenWindow
): Promise<CaptureRefusal | null> {
  const app = { name: window.appName, bundleId: window.bundleId };
  const appRefusal = decideAppCapture(settings, app);
  if (appRefusal !== null) return appRefusal;
  const surface = captureSurface(app);
  const page =
    surface === 'chrome' || surface === 'safari'
      ? boundBrowserWindow(await deps.readBrowserWindows(surface), window)
      : null;
  return decideWindowContents(settings, { app, surface, title: window.title, page });
}

/**
 * The browser's own account of the captured window.
 *
 * A browser names its windows by its own ids, not by the CoreGraphics id that is
 * captured, so the two are tied by frame and title: exactly one browser window must
 * match both. None, or more than one, means the page cannot be tied to the pixels.
 */
function boundBrowserWindow(
  observed: BrowserWindowObservation[] | null,
  window: OnScreenWindow
): BrowserWindowObservation | null {
  if (observed === null || window.title === null) return null;
  const matches = observed.filter(
    (candidate) => candidate.title === window.title && sameFrame(candidate.bounds, window.bounds)
  );
  return matches.length === 1 ? matches[0] : null;
}

function sameFrame(left: WindowBounds, right: WindowBounds): boolean {
  return (['x', 'y', 'width', 'height'] as const).every(
    (key) => Math.abs(left[key] - right[key]) <= FRAME_MATCH_TOLERANCE_POINTS
  );
}

function storeCapture(
  deps: ScreenCaptureDeps,
  params: { captured: CapturedScreenImage; appName: string }
): ScreenCaptureAnswer {
  const userId = deps.getCurrentSubjectId();
  if (userId === null) throw new Error('Missing authenticated user id.');
  const now = deps.now();
  const storagePath = `${userId}/${imageStorageDateSegment(now)}/${randomUUID()}.png`;
  // The user id comes from the access token, so a value that cannot form a storage
  // path is a broken session rather than a refusable capture: write nothing at all.
  if (!isValidImageStoragePath({ userId, storagePath })) {
    throw new Error('Refusing to store a capture outside the user image namespace.');
  }
  const localArtifactRoot = deps.localArtifactRoot();
  deps.writeFileAtomic(
    storedImageAbsolutePath(localArtifactRoot, storagePath),
    path.join(localArtifactRoot, '.tmp', 'generated-images'),
    params.captured.png
  );
  return {
    status: 'captured',
    storage_path: storagePath,
    mime_type: 'image/png',
    byte_size: params.captured.png.byteLength,
    sha256: createHash('sha256').update(params.captured.png).digest('hex'),
    width_px: params.captured.widthPx,
    height_px: params.captured.heightPx,
    app_name: params.appName,
    captured_at: now.toISOString(),
  };
}
