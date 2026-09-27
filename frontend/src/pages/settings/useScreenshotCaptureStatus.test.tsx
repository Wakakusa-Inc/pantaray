import { act, cleanup, renderHook, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import type { RecordingStartResult } from '../../../electron/src/screenshot/screenshotSync';
import { useScreenshotCaptureStatus } from './useScreenshotCaptureStatus';

function stubScreenshotBridge(start: () => Promise<RecordingStartResult>, isCapturing = false) {
  window.electron = {
    screenshot: {
      getStatus: vi.fn(async () => isCapturing),
      onStatusChanged: vi.fn(() => () => undefined),
      start,
      stop: vi.fn(async () => true),
    },
  } as unknown as Window['electron'];
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((yes) => {
    resolve = yes;
  });
  return { promise, resolve };
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  delete window.electron;
});

describe('useScreenshotCaptureStatus', () => {
  it('turns recording on with no filter prerequisite', async () => {
    const start = vi.fn(async (): Promise<RecordingStartResult> => 'started');
    stubScreenshotBridge(start);

    const { result } = renderHook(useScreenshotCaptureStatus);

    await waitFor(() => {
      expect(result.current.isCapturingScreenshots).toBe(false);
    });
    await act(async () => {
      await result.current.setScreenshotsEnabled(true);
    });

    expect(start).toHaveBeenCalledTimes(1);
  });

  it('keeps a newer notification when the initial status arrives late', async () => {
    const initial = deferred<boolean>();
    stubScreenshotBridge(vi.fn(async () => 'started' as const));
    let notify!: (value: boolean) => void;
    vi.spyOn(window.electron!.screenshot!, 'getStatus').mockReturnValue(initial.promise);
    vi.spyOn(window.electron!.screenshot!, 'onStatusChanged').mockImplementation((listener) => {
      notify = listener;
      return () => undefined;
    });
    const { result } = renderHook(useScreenshotCaptureStatus);
    act(() => notify(true));
    await act(async () => initial.resolve(false));
    expect(result.current.isCapturingScreenshots).toBe(true);
  });

  it('reports unavailable on a failed read and recovers from a later notification', async () => {
    stubScreenshotBridge(vi.fn(async () => 'started' as const));
    vi.spyOn(console, 'error').mockImplementation(() => undefined);
    vi.spyOn(window.electron!.screenshot!, 'getStatus').mockRejectedValue(new Error('unavailable'));
    let notify!: (value: boolean) => void;
    vi.spyOn(window.electron!.screenshot!, 'onStatusChanged').mockImplementation((listener) => {
      notify = listener;
      return () => undefined;
    });
    const { result } = renderHook(useScreenshotCaptureStatus);
    await waitFor(() => expect(result.current.captureStatusUnavailable).toBe(true));
    expect(result.current.isCapturingScreenshots).toBeNull();
    expect(result.current.isScreenshotCaptureAvailable).toBe(false);
    act(() => notify(true));
    expect(result.current.captureStatusUnavailable).toBe(false);
    expect(result.current.isCapturingScreenshots).toBe(true);
  });

  it('rejects a second capture operation dispatched while the first is still running', async () => {
    // The toggle is drawn from the status main reports, which a start has not changed
    // yet: a second press before the first answers would send a second permit request.
    const pendingStart = deferred<RecordingStartResult>();
    const start = vi.fn(() => pendingStart.promise);
    stubScreenshotBridge(start);
    const { result } = renderHook(useScreenshotCaptureStatus);
    await waitFor(() => expect(result.current.isCapturingScreenshots).toBe(false));

    let first!: Promise<RecordingStartResult>;
    await act(async () => {
      first = result.current.startRecording();
      expect(await result.current.startRecording()).toBe('failed');
    });
    expect(start).toHaveBeenCalledTimes(1);
    expect(result.current.isProcessing).toBe(true);

    await act(async () => {
      pendingStart.resolve('started');
      expect(await first).toBe('started');
    });
    expect(result.current.isProcessing).toBe(false);
  });
});
