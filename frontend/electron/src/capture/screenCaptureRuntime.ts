/**
 * Electron side of one `capture_screen` request: real windows, real answer.
 *
 * `screenCapture.ts` owns the decision and knows nothing about macOS; this file
 * supplies the platform it decides against and posts the answer back to the local
 * backend. Splitting them is what lets the gates be tested without a display.
 *
 * Windows are read through CoreGraphics from JXA, browsers are asked over Apple
 * Events, and the one window is captured with the system `screencapture` tool, so no
 * pixel of any other window is read. All three run as children of this app and act
 * under its Screen Recording and Automation permissions.
 *
 * An unexpected failure here posts nothing. The waiting tool then times out and
 * reports that no image was taken, which is the same fail-closed outcome as a
 * desktop app that is not running - and strictly better than inventing a refusal
 * reason the user never gave.
 */

import { nativeImage, systemPreferences } from 'electron';
import { randomUUID } from 'node:crypto';
import { execFile } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import { promisify } from 'node:util';

import { writeFileAtomic } from '../atomicFile';
import type { CapturePrivacySettings } from '../privacy/capturePrivacy';
import type { BrowserWindowObservation } from '../privacy/windowCapturePolicy';
import {
  answerScreenCapture,
  type CapturedScreenImage,
  type OnScreenWindow,
  type ScreenCaptureAnswer,
  type ScreenCaptureRequest,
} from './screenCapture';

const run = promisify(execFile);

/** Each child gets a share of the 15 s the Action waits for the whole answer. */
const CHILD_TIMEOUT_MS = 4_000;

/** On-screen, layer-0 windows of regular apps, frontmost first. */
const LIST_WINDOWS_SCRIPT = `
ObjC.import('AppKit');
ObjC.import('CoreGraphics');
function run() {
  const apps = {};
  for (const app of ObjC.unwrap($.NSWorkspace.sharedWorkspace.runningApplications)) {
    if (app.activationPolicy !== $.NSApplicationActivationPolicyRegular) continue;
    apps[app.processIdentifier] = {
      name: ObjC.unwrap(app.localizedName),
      bundleId: ObjC.unwrap(app.bundleIdentifier) || null,
    };
  }
  const options = $.kCGWindowListOptionOnScreenOnly | $.kCGWindowListExcludeDesktopElements;
  const windows = ObjC.deepUnwrap(
    ObjC.castRefToObject($.CGWindowListCopyWindowInfo(options, $.kCGNullWindowID))
  );
  return JSON.stringify(
    windows
      .filter((window) => window.kCGWindowLayer === 0 && apps[window.kCGWindowOwnerPID])
      .map((window) => {
        const app = apps[window.kCGWindowOwnerPID];
        const bounds = window.kCGWindowBounds;
        return {
          windowId: window.kCGWindowNumber,
          appName: app.name,
          bundleId: app.bundleId,
          title: window.kCGWindowName === undefined ? null : window.kCGWindowName,
          alpha: window.kCGWindowAlpha,
          bounds: { x: bounds.X, y: bounds.Y, width: bounds.Width, height: bounds.Height },
        };
      })
  );
}`;

/** Every window of the browser, each with its active tab; one property per Apple Event. */
const BROWSER_WINDOWS_SCRIPTS: Record<'chrome' | 'safari', string> = {
  chrome: `
function run() {
  const windows = Application('com.google.Chrome').windows;
  const titles = windows.name();
  const bounds = windows.bounds();
  const urls = windows.activeTab.url();
  const modes = windows.mode();
  return JSON.stringify(titles.map((title, index) => ({
    title, bounds: bounds[index], url: urls[index] || null, mode: modes[index] || null,
  })));
}`,
  safari: `
function run() {
  const windows = Application('com.apple.Safari').windows;
  const titles = windows.name();
  const bounds = windows.bounds();
  const urls = windows.currentTab.url();
  return JSON.stringify(titles.map((title, index) => ({
    title, bounds: bounds[index], url: urls[index] || null, mode: null,
  })));
}`,
};

async function runJxa(script: string): Promise<string> {
  const { stdout } = await run('/usr/bin/osascript', ['-l', 'JavaScript', '-e', script], {
    timeout: CHILD_TIMEOUT_MS,
  });
  return stdout;
}

async function listWindows(): Promise<OnScreenWindow[]> {
  return JSON.parse(await runJxa(LIST_WINDOWS_SCRIPT)) as OnScreenWindow[];
}

async function readBrowserWindows(
  browser: 'chrome' | 'safari'
): Promise<BrowserWindowObservation[] | null> {
  let stdout: string;
  try {
    stdout = await runJxa(BROWSER_WINDOWS_SCRIPTS[browser]);
  } catch {
    // Automation not granted, the browser not answering in time: either way its page
    // is unknown, and the capture is refused as one whose URL cannot be read.
    return null;
  }
  return JSON.parse(stdout) as BrowserWindowObservation[];
}

/**
 * Capture one window at its logical size.
 *
 * Design limit: a Retina window is stored at 1x, so the PNG stays a few megabytes
 * instead of tens. Drop the resize if small on-screen text turns out to be
 * unreadable to the model.
 */
async function captureWindow(
  localArtifactRoot: string,
  window: OnScreenWindow
): Promise<CapturedScreenImage | null> {
  const directory = path.join(localArtifactRoot, '.tmp', 'screen-captures');
  fs.mkdirSync(directory, { recursive: true });
  const file = path.join(directory, `${randomUUID()}.png`);
  try {
    try {
      await run(
        '/usr/sbin/screencapture',
        [`-l${window.windowId}`, '-o', '-x', '-t', 'png', file],
        {
          timeout: CHILD_TIMEOUT_MS,
        }
      );
    } catch {
      // screencapture exits non-zero when the window has gone; there is no image.
      return null;
    }
    const image = nativeImage.createFromPath(file);
    if (image.isEmpty()) return null;
    const logicalWidth = Math.round(window.bounds.width);
    const stored =
      image.getSize().width > logicalWidth
        ? image.resize({ width: logicalWidth, quality: 'best' })
        : image;
    const size = stored.getSize();
    return { png: stored.toPNG(), widthPx: size.width, heightPx: size.height };
  } finally {
    fs.rmSync(file, { force: true });
  }
}

export function createScreenCaptureResponder(params: {
  getCaptureSettings: () => CapturePrivacySettings;
  isCaptureEditing: () => boolean;
  getCurrentSubjectId: () => string | null;
  localArtifactRoot: string;
  postAnswer: (body: {
    capture_request_id: string;
    result: ScreenCaptureAnswer;
  }) => Promise<unknown>;
  logger?: { error?: (name: string, payload?: unknown) => void } | null;
}): (request: ScreenCaptureRequest) => Promise<void> {
  return async (request) => {
    try {
      const result = await answerScreenCapture(
        {
          readScreenRecordingStatus: () => systemPreferences.getMediaAccessStatus('screen'),
          getCaptureSettings: params.getCaptureSettings,
          isCaptureEditing: params.isCaptureEditing,
          listWindows,
          readBrowserWindows,
          captureWindow: (window) => captureWindow(params.localArtifactRoot, window),
          getCurrentSubjectId: params.getCurrentSubjectId,
          localArtifactRoot: () => params.localArtifactRoot,
          writeFileAtomic,
          now: () => new Date(),
        },
        request.appName
      );
      await params.postAnswer({
        capture_request_id: request.captureRequestId,
        result,
      });
    } catch (error) {
      params.logger?.error?.('SCREEN_CAPTURE_REQUEST_ERR', {
        capture_request_id: request.captureRequestId,
        err: error,
      });
    }
  };
}
