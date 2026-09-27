/**
 * Electron side of one `capture_screen` request: real screen, real answer.
 *
 * `screenCapture.ts` owns the decision and knows nothing about Electron; this file
 * supplies the platform it decides against and posts the answer back to the local
 * backend. Splitting them is what lets the gates be tested without a display.
 *
 * An unexpected failure here posts nothing. The waiting tool then times out and
 * reports that no image was taken, which is the same fail-closed outcome as a
 * desktop app that is not running - and strictly better than inventing a refusal
 * reason the user never gave.
 */

import { desktopCapturer, screen, systemPreferences } from 'electron';
import { promisify } from 'node:util';
import { exec } from 'node:child_process';
import { writeFileAtomic } from '../atomicFile';

import type { CapturePrivacySettings } from '../privacy/capturePrivacy';
import {
  answerScreenCapture,
  type CapturedScreenImage,
  type FrontmostApplication,
  type ScreenCaptureAnswer,
  type ScreenCaptureRequest,
} from './screenCapture';

const execPromise = promisify(exec);

type ScreenshotProbes = {
  readFrontmostApplication: (
    run: typeof execPromise
  ) => Promise<{ name: string; bundleId: string | null } | null>;
  probeBrowserUrlForApp: (
    run: typeof execPromise,
    appName: string
  ) => Promise<{ url: string | null }>;
};

function loadScreenshotProbes(): ScreenshotProbes {
  // screenshot.js is CommonJS; load via require.
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  return require('../../screenshot.js');
}

/**
 * Capture the primary display at its logical size.
 *
 * Design limit: a Retina display is captured at 1x, so the PNG stays a few
 * megabytes instead of tens. Raise it to `size * scaleFactor` if small on-screen
 * text turns out to be unreadable to the model.
 */
async function capturePrimaryDisplay(): Promise<CapturedScreenImage | null> {
  const display = screen.getPrimaryDisplay();
  const sources = await desktopCapturer.getSources({
    types: ['screen'],
    thumbnailSize: display.size,
  });
  const source =
    sources.find((candidate) => String(candidate.display_id) === String(display.id)) ?? sources[0];
  if (!source || source.thumbnail.isEmpty()) return null;
  const size = source.thumbnail.getSize();
  return { png: source.thumbnail.toPNG(), widthPx: size.width, heightPx: size.height };
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
      const probes = loadScreenshotProbes();
      const result = await answerScreenCapture({
        readScreenRecordingStatus: () => systemPreferences.getMediaAccessStatus('screen'),
        getCaptureSettings: params.getCaptureSettings,
        isCaptureEditing: params.isCaptureEditing,
        readFrontmostApplication: async (): Promise<FrontmostApplication | null> =>
          probes.readFrontmostApplication(execPromise),
        readBrowserUrl: async (appName) =>
          (await probes.probeBrowserUrlForApp(execPromise, appName)).url,
        capturePrimaryDisplay,
        getCurrentSubjectId: params.getCurrentSubjectId,
        localArtifactRoot: () => params.localArtifactRoot,
        writeFileAtomic,
        now: () => new Date(),
      });
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
