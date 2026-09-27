/**
 * Answering one `capture_screen` request from the Action runtime.
 *
 * The runtime cannot see the screen and cannot decide whether it may: the macOS
 * Screen Recording permission and the user's recording filter both live here. It
 * asks, this module decides, and the answer goes back over the local backend.
 *
 * Every gate runs before a single pixel is read, so a refusal is a decision rather
 * than a deletion - there is never an image to discard. The gates, in the order
 * they settle:
 *
 * 1. Screen Recording permission. Without it macOS returns a desktop picture with
 *    no windows, which looks like a successful capture and is not one.
 * 2. Which application is frontmost. If that cannot be read, no filter can be
 *    applied to it, so the capture is refused.
 * 3. Password managers, whatever the filter says. See `alwaysDeniedCaptureApps`.
 * 4. Filter editing in progress: while the user is changing the rules, the rules
 *    that would apply are not settled.
 * 5. The app filter, then - for a browser - the page's own URL: sign-in and payment
 *    pages are refused whatever the filter says, exactly as the always-on recorder
 *    refuses them (`privacy/browserUrlPolicy.ts`), and the website filter decides the
 *    rest. A browser that reports no URL is refused rather than captured unfiltered.
 *
 * A refusal may name the application or the browser host; it never carries the window
 * title, which is often the private thing the filter exists to protect. A sign-in or
 * payment page names neither host nor path: the route is what gave the page away, and
 * repeating it would leak what the refusal was protecting.
 */

import { createHash, randomUUID } from 'crypto';
import path from 'path';

import {
  captureAppKey,
  type CaptureAppEntry,
  type CapturePrivacySettings,
} from '../privacy/capturePrivacy';
import { isAlwaysDeniedCaptureApp } from '../privacy/alwaysDeniedCaptureApps';
import { decideBrowserUrl } from '../privacy/browserUrlPolicy';
import { storedImageAbsolutePath } from '../protocol/imageProtocol';
import { imageStorageDateSegment, isValidImageStoragePath } from '../protocol/imageStoragePath';

/** Browsers whose active tab URL the website filter can actually be applied to. */
const FILTERABLE_BROWSER_APP_NAMES = new Set(['Google Chrome', 'Safari']);

export type ScreenCaptureRequest = {
  captureRequestId: string;
  actionId: string;
  processId: string;
  toolRequestId: string;
};

export type FrontmostApplication = { name: string; bundleId: string | null };

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
  | {
      status: 'refused';
      code:
        | 'SCREEN_RECORDING_PERMISSION_REQUIRED'
        | 'CAPTURE_REFUSED_BY_PRIVACY_FILTER'
        | 'CAPTURE_REFUSED_PASSWORD_MANAGER'
        | 'CAPTURE_REFUSED_URL_UNAVAILABLE'
        | 'CAPTURE_REFUSED_SENSITIVE_PAGE';
      axis?: 'app' | 'website' | 'editing';
      app_name?: string;
      host?: string;
    };

export type ScreenCaptureDeps = {
  /** `systemPreferences.getMediaAccessStatus('screen')`. */
  readScreenRecordingStatus: () => string;
  getCaptureSettings: () => CapturePrivacySettings;
  isCaptureEditing: () => boolean;
  /** Frontmost application, or null when it cannot be identified. */
  readFrontmostApplication: () => Promise<FrontmostApplication | null>;
  /** Active tab URL of a supported browser, or null when it cannot be read. */
  readBrowserUrl: (appName: string) => Promise<string | null>;
  capturePrimaryDisplay: () => Promise<CapturedScreenImage | null>;
  getCurrentSubjectId: () => string | null;
  localArtifactRoot: () => string;
  writeFileAtomic: (targetPath: string, tempDirectoryPath: string, payload: Buffer) => void;
  now: () => Date;
};

export async function answerScreenCapture(deps: ScreenCaptureDeps): Promise<ScreenCaptureAnswer> {
  if (deps.readScreenRecordingStatus() !== 'granted') {
    return { status: 'refused', code: 'SCREEN_RECORDING_PERMISSION_REQUIRED' };
  }

  const frontmost = await deps.readFrontmostApplication();
  if (frontmost === null) {
    return { status: 'refused', code: 'CAPTURE_REFUSED_BY_PRIVACY_FILTER', axis: 'app' };
  }
  if (frontmost.bundleId === null) {
    // Filter entries are keyed by bundle id; without one, an excluded app would read
    // as "not listed" and pass. The name alone is not evidence the filter accepts.
    return {
      status: 'refused',
      code: 'CAPTURE_REFUSED_BY_PRIVACY_FILTER',
      axis: 'app',
      app_name: frontmost.name,
    };
  }
  if (isAlwaysDeniedCaptureApp(frontmost)) {
    return {
      status: 'refused',
      code: 'CAPTURE_REFUSED_PASSWORD_MANAGER',
      app_name: frontmost.name,
    };
  }
  if (deps.isCaptureEditing()) {
    return { status: 'refused', code: 'CAPTURE_REFUSED_BY_PRIVACY_FILTER', axis: 'editing' };
  }

  const settings = deps.getCaptureSettings();
  if (!isAppAllowed(settings, frontmost)) {
    return {
      status: 'refused',
      code: 'CAPTURE_REFUSED_BY_PRIVACY_FILTER',
      axis: 'app',
      app_name: frontmost.name,
    };
  }
  if (FILTERABLE_BROWSER_APP_NAMES.has(frontmost.name)) {
    const page = decideBrowserUrl(await deps.readBrowserUrl(frontmost.name));
    if (page.kind === 'unavailable') {
      return {
        status: 'refused',
        code: 'CAPTURE_REFUSED_URL_UNAVAILABLE',
        app_name: frontmost.name,
      };
    }
    if (page.kind === 'sensitive') {
      return {
        status: 'refused',
        code: 'CAPTURE_REFUSED_SENSITIVE_PAGE',
        app_name: frontmost.name,
      };
    }
    if (!isHostAllowed(settings, page.host)) {
      return {
        status: 'refused',
        code: 'CAPTURE_REFUSED_BY_PRIVACY_FILTER',
        axis: 'website',
        app_name: frontmost.name,
        host: page.host,
      };
    }
  }

  const captured = await deps.capturePrimaryDisplay();
  if (captured === null) {
    // The permission is granted but the display produced no frame; the request is
    // answered as a permission problem rather than left to time out.
    return { status: 'refused', code: 'SCREEN_RECORDING_PERMISSION_REQUIRED' };
  }
  return storeCapture(deps, { captured, appName: frontmost.name });
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

function isAppAllowed(settings: CapturePrivacySettings, frontmost: FrontmostApplication): boolean {
  const listed = settings.apps.entries.some((entry: CaptureAppEntry) =>
    matchesApp(entry, frontmost)
  );
  return settings.apps.mode === 'exclude' ? !listed : listed;
}

function matchesApp(entry: CaptureAppEntry, frontmost: FrontmostApplication): boolean {
  const key = captureAppKey(entry).toLowerCase();
  if (frontmost.bundleId !== null && key === frontmost.bundleId.toLowerCase()) return true;
  // A name-only entry is the recorder's fallback for a bundle with no identifier.
  return entry.bundleId === null && key === frontmost.name.trim().toLowerCase();
}

function isHostAllowed(settings: CapturePrivacySettings, host: string): boolean {
  const listed = settings.websites.hosts.includes(host);
  return settings.websites.mode === 'exclude' ? !listed : listed;
}
