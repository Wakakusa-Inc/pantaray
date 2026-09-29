import { promises as fs } from 'node:fs';
import path from 'node:path';

import type { MainContext } from '../context';
import type { IpcRegistrar } from '../registrar';
import { buildFrontendDevPageUrl } from '../../runtime/devFrontendEnv';
import {
  computeCaptureWindowHeight,
  computeResize,
  computeShareCardCapturePlan,
  type ShareCardNativeImage,
  type ShareCardNativeImageFactory,
} from './shareCardImage';

type ShareCardCapturePayload = {
  content: string | null;
  suggestionText: string;
  isSuggestionStreamFinished: boolean;
  isSuggestionAccepted: boolean;
  actionText: string;
  isActionStreamFinished: boolean;
  isActionPhase: boolean;
};

type ShareCardReadyPayload = {
  height: number;
};

type ShareCardCaptureResult =
  | { ok: true; clipboardOk: boolean; downloadOk: boolean; filename: string; path?: string }
  | { ok: false; error: string };

type ShareCardWindowEvent = {
  sender?: { id?: unknown };
};

type ShareCardDebugger = {
  attach: (protocolVersion?: string) => void;
  detach: () => void;
  isAttached: () => boolean;
  sendCommand: (method: string, commandParams?: unknown) => Promise<unknown>;
};

type ShareCardWebContents = {
  id: number;
  send: (channel: string, ...args: unknown[]) => void;
  capturePage: (
    rect?: { x: number; y: number; width: number; height: number },
    opts?: { stayHidden?: boolean }
  ) => Promise<ShareCardNativeImage>;
  executeJavaScript: (code: string) => Promise<unknown>;
  once: (event: string, cb: () => void) => void;
  on?: (event: string, cb: () => void) => void;
  debugger: ShareCardDebugger;
};

type ShareCardBrowserWindow = {
  webContents: ShareCardWebContents;
  loadURL: (url: string) => Promise<void>;
  loadFile: (filePath: string, options?: { query?: Record<string, string> }) => Promise<void>;
  setContentSize: (w: number, h: number) => void;
  destroy: () => void;
  isDestroyed: () => boolean;
  on?: (event: string, cb: () => void) => void;
};

type ElectronShareCardModule = {
  app: { isPackaged: boolean; getPath: (name: string) => string };
  clipboard: { writeImage: (img: ShareCardNativeImage) => void };
  nativeImage: ShareCardNativeImageFactory;
  BrowserWindow: new (opts: {
    width: number;
    height: number;
    useContentSize: boolean;
    show: boolean;
    frame: boolean;
    transparent: boolean;
    backgroundColor: string;
    focusable: boolean;
    resizable: boolean;
    webPreferences: {
      preload: string;
      contextIsolation: boolean;
      sandbox: boolean;
      nodeIntegration: boolean;
      devTools: boolean;
      backgroundThrottling: boolean;
    };
  }) => ShareCardBrowserWindow;
};

const MAX_PNG_BYTES = 25 * 1024 * 1024; // 25MB
const READY_TIMEOUT_MS = 10_000;
// ShareCard は「通常のOverlay（幅 520px）」と同じ折り返しで描画する。
// 撮影ウィンドウは 584px (card 520px + margin 32px*2) で、card は中央配置。
// カード幅の実体は renderer 側の --sharecard-card-width-px（src/index.css）で、
// overlay_window_factory.js の DEFAULT_OVERLAY_WIDTH_PX と一致させること。
const SHARECARD_STAGE_WIDTH_PX = 584;
const FINAL_LAYOUT_WAIT_SCRIPT =
  'new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)))';
const CHROME_DEBUGGER_PROTOCOL_VERSION = '1.3';
const MEASURE_SHARECARD_HEIGHT_SCRIPT = `(() => {
  const parsePx = (value) => {
    const parsed = Number.parseFloat(value || '0');
    return Number.isFinite(parsed) ? parsed : 0;
  };
  const outerHeight = (element) => {
    if (!element) return 0;
    const rect = element.getBoundingClientRect();
    const style = window.getComputedStyle(element);
    return rect.height + parsePx(style.marginTop) + parsePx(style.marginBottom);
  };
  const stage = document.querySelector('.sharecard-stage');
  const card = document.querySelector('.sharecard-card');
  return Math.ceil(Math.max(
    document.documentElement?.scrollHeight || 0,
    document.body?.scrollHeight || 0,
    stage?.scrollHeight || 0,
    stage?.getBoundingClientRect().height || 0,
    outerHeight(card)
  ));
})()`;

const pendingReadyByWebContentsId = new Map<
  number,
  {
    resolve: (height: number) => void;
    reject: (err: Error) => void;
    timer: NodeJS.Timeout;
  }
>();

function safeString(raw: unknown, maxLen: number): string | null {
  if (typeof raw !== 'string') return null;
  const s = raw;
  if (s.length > maxLen) return null;
  return s;
}

function safeBool(raw: unknown): boolean | null {
  if (typeof raw !== 'boolean') return null;
  return raw;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object';
}

function getSenderWebContentsId(event: unknown): number | null {
  if (!isRecord(event)) return null;
  const senderId = (event as ShareCardWindowEvent).sender?.id;
  return typeof senderId === 'number' ? senderId : null;
}

function normalizeCapturePayload(raw: unknown): ShareCardCapturePayload | null {
  if (!isRecord(raw)) return null;
  const p = raw;

  // DoS対策: 合計文字数に上限を付ける
  if (!('content' in p)) return null;
  if (!('suggestionText' in p)) return null;
  if (!('actionText' in p)) return null;
  if (!('isSuggestionStreamFinished' in p)) return null;
  if (!('isSuggestionAccepted' in p)) return null;
  if (!('isActionStreamFinished' in p)) return null;
  if (!('isActionPhase' in p)) return null;

  const content = p.content === null ? null : safeString(p.content, 600_000);
  const suggestionText = safeString(p.suggestionText, 600_000);
  const actionText = safeString(p.actionText, 1_200_000);
  const isSuggestionStreamFinished = safeBool(p.isSuggestionStreamFinished);
  const isSuggestionAccepted = safeBool(p.isSuggestionAccepted);
  const isActionStreamFinished = safeBool(p.isActionStreamFinished);
  const isActionPhase = safeBool(p.isActionPhase);

  if (suggestionText === null) return null;
  if (actionText === null) return null;
  if (content === null && p.content !== null) return null;
  if (isSuggestionStreamFinished === null) return null;
  if (isSuggestionAccepted === null) return null;
  if (isActionStreamFinished === null) return null;
  if (isActionPhase === null) return null;

  const totalLen = (content?.length ?? 0) + suggestionText.length + actionText.length;
  if (totalLen > 1_800_000) return null;

  return {
    content,
    suggestionText,
    isSuggestionStreamFinished,
    isSuggestionAccepted,
    actionText,
    isActionStreamFinished,
    isActionPhase,
  };
}

function normalizeReadyPayload(raw: unknown): ShareCardReadyPayload | null {
  if (!isRecord(raw)) return null;
  const p = raw;
  const h = p.height;
  if (typeof h !== 'number' || !Number.isFinite(h)) return null;
  const height = Math.floor(h);
  // 0 や異常値は弾く
  if (height < 100 || height > 200_000) return null;
  return { height };
}

function formatShareTimestamp(d: Date): string {
  const pad2 = (n: number) => String(n).padStart(2, '0');
  const pad3 = (n: number) => String(n).padStart(3, '0');
  const yyyy = d.getFullYear();
  const mm = pad2(d.getMonth() + 1);
  const dd = pad2(d.getDate());
  const hh = pad2(d.getHours());
  const mi = pad2(d.getMinutes());
  const ss = pad2(d.getSeconds());
  const ms = pad3(d.getMilliseconds());
  return `${yyyy}${mm}${dd}-${hh}${mi}${ss}-${ms}`;
}

function isDevRuntime(app: { isPackaged: boolean }): boolean {
  return String(process.env.NODE_ENV || '').toLowerCase() === 'development' || !app.isPackaged;
}

function resolveFrontendRoot(): string {
  // __dirname は `.../frontend/electron/(src|dist)/ipc/handlers` を想定
  return path.resolve(__dirname, '../../../..');
}

function resolveElectronRoot(): string {
  return path.resolve(__dirname, '../../..');
}

function getShareCardUrl(app: {
  isPackaged: boolean;
}):
  | { kind: 'url'; url: string }
  | { kind: 'file'; filePath: string; query: Record<string, string> } {
  const isDev = isDevRuntime(app);
  if (isDev) {
    const u = new URL(buildFrontendDevPageUrl('/notification.html'));
    u.searchParams.set('mode', 'sharecard');
    return { kind: 'url', url: u.toString() };
  }
  const frontendRoot = resolveFrontendRoot();
  const filePath = path.join(frontendRoot, 'dist', 'notification.html');
  return { kind: 'file', filePath, query: { mode: 'sharecard' } };
}

async function waitForReady(webContentsId: number): Promise<number> {
  return await new Promise<number>((resolve, reject) => {
    const timer = setTimeout(() => {
      pendingReadyByWebContentsId.delete(webContentsId);
      reject(new Error('ShareCard render timed out.'));
    }, READY_TIMEOUT_MS);
    pendingReadyByWebContentsId.set(webContentsId, { resolve, reject, timer });
  });
}

function buildPrepareCaptureDocumentScript(totalHeight: number): string {
  return `(() => {
    const root = document.getElementById('root');
    const stage = document.querySelector('.sharecard-stage');
    if (!(stage instanceof HTMLElement)) return false;
    document.documentElement.style.height = '${totalHeight}px';
    document.documentElement.style.minHeight = '${totalHeight}px';
    document.documentElement.style.overflow = 'visible';
    document.body.style.height = '${totalHeight}px';
    document.body.style.minHeight = '${totalHeight}px';
    document.body.style.overflow = 'visible';
    if (root instanceof HTMLElement) {
      root.style.height = '${totalHeight}px';
      root.style.minHeight = '${totalHeight}px';
      root.style.overflow = 'visible';
    }
    stage.style.height = '${totalHeight}px';
    stage.style.minHeight = '${totalHeight}px';
    stage.style.alignItems = 'flex-start';
    stage.style.transform = '';
    stage.style.transformOrigin = '';
    return true;
  })()`;
}

function readCapturedPng(result: unknown): Buffer {
  if (!isRecord(result) || typeof result.data !== 'string') {
    throw new Error('ShareCard screenshot response is invalid.');
  }
  return Buffer.from(result.data, 'base64');
}

async function captureFullShareCard(
  nativeImage: ShareCardNativeImageFactory,
  bw: ShareCardBrowserWindow,
  measuredHeight: number
): Promise<ShareCardNativeImage> {
  const captureHeight = computeCaptureWindowHeight(measuredHeight);
  const viewportHeight = computeShareCardCapturePlan(captureHeight).viewportHeight;
  bw.setContentSize(SHARECARD_STAGE_WIDTH_PX, viewportHeight);
  await bw.webContents.executeJavaScript(buildPrepareCaptureDocumentScript(captureHeight));
  await bw.webContents.executeJavaScript(FINAL_LAYOUT_WAIT_SCRIPT);

  const debuggerClient = bw.webContents.debugger;
  const wasAttached = debuggerClient.isAttached();
  if (!wasAttached) debuggerClient.attach(CHROME_DEBUGGER_PROTOCOL_VERSION);

  try {
    await debuggerClient.sendCommand('Emulation.setDeviceMetricsOverride', {
      width: SHARECARD_STAGE_WIDTH_PX,
      height: captureHeight,
      deviceScaleFactor: 1,
      mobile: false,
      screenWidth: SHARECARD_STAGE_WIDTH_PX,
      screenHeight: captureHeight,
    });
    await bw.webContents.executeJavaScript(FINAL_LAYOUT_WAIT_SCRIPT);
    const result = await debuggerClient.sendCommand('Page.captureScreenshot', {
      format: 'png',
      fromSurface: true,
      captureBeyondViewport: true,
      clip: {
        x: 0,
        y: 0,
        width: SHARECARD_STAGE_WIDTH_PX,
        height: captureHeight,
        scale: 1,
      },
    });
    return nativeImage.createFromBuffer(readCapturedPng(result));
  } finally {
    try {
      await debuggerClient.sendCommand('Emulation.clearDeviceMetricsOverride');
    } catch {
      // no-op
    }
    if (!wasAttached && debuggerClient.isAttached()) debuggerClient.detach();
  }
}

function rejectPendingReady(webContentsId: number, message: string): void {
  const pending = pendingReadyByWebContentsId.get(webContentsId);
  if (!pending) return;
  pendingReadyByWebContentsId.delete(webContentsId);
  clearTimeout(pending.timer);
  pending.reject(new Error(message));
}

async function savePngToDownloads(
  electronApp: { getPath: (name: string) => string },
  bytes: Uint8Array,
  filename: string
): Promise<{ ok: true; path: string } | { ok: false; error: string }> {
  try {
    if (bytes.length > MAX_PNG_BYTES) {
      return { ok: false, error: 'PNG is too large.' };
    }
    const downloadsDir = electronApp.getPath('downloads');
    if (!downloadsDir) return { ok: false, error: 'Downloads folder not found.' };
    const outPath = path.join(downloadsDir, filename);
    await fs.writeFile(outPath, bytes, { flag: 'wx' });
    return { ok: true, path: outPath };
  } catch (e) {
    const code = isRecord(e) ? e.code : null;
    if (code === 'EEXIST') return { ok: false, error: 'File already exists.' };
    if (code === 'EACCES' || code === 'EPERM') return { ok: false, error: 'Permission denied.' };
    if (code === 'ENOENT') return { ok: false, error: 'Downloads folder not found.' };
    return { ok: false, error: 'Failed to save PNG.' };
  }
}

export function registerShareCardHandlers(_ctx: MainContext, registrar: IpcRegistrar): void {
  // renderer(sharecard mode) -> main: layout ready
  registrar.on('sharecard:ready', (event, payload) => {
    try {
      const p = normalizeReadyPayload(payload);
      if (!p) return;
      const webContentsId = getSenderWebContentsId(event);
      if (webContentsId == null) return;
      const pending = pendingReadyByWebContentsId.get(webContentsId);
      if (!pending) return;
      pendingReadyByWebContentsId.delete(webContentsId);
      clearTimeout(pending.timer);
      pending.resolve(p.height);
    } catch (e) {
      // best-effort
      try {
        const webContentsId = getSenderWebContentsId(event);
        if (webContentsId == null) return;
        const pending = pendingReadyByWebContentsId.get(webContentsId);
        if (!pending) return;
        pendingReadyByWebContentsId.delete(webContentsId);
        clearTimeout(pending.timer);
        pending.reject(e instanceof Error ? e : new Error('ShareCard ready failed.'));
      } catch {
        // no-op
      }
    }
  });

  registrar.handle(
    'share:captureShareCard',
    async (_evt, payload: unknown): Promise<ShareCardCaptureResult> => {
      let win: ShareCardBrowserWindow | null = null;
      let sender: ShareCardWebContents | null = null;
      let webContentsId: number | null = null;
      try {
        const cap = normalizeCapturePayload(payload);
        if (!cap) return { ok: false, error: 'Invalid share payload.' };

        // eslint-disable-next-line @typescript-eslint/no-require-imports
        const electron = require('electron') as ElectronShareCardModule;

        const isDev = isDevRuntime(electron.app);
        // SECURITY: sharecard では最小限の preload を使い、不要なIPC invoke等を露出しない
        const preloadPath = path.join(resolveElectronRoot(), 'preload_sharecard.js');
        const urlSpec = getShareCardUrl(electron.app);

        // NOTE:
        // - ウィンドウ幅は card(520px) + 左右margin(32px) の 584px。card は中央配置。
        // - 撮影は等倍（deviceScaleFactor: 1）で、共有画像は幅 1600px へリサイズする。
        win = new electron.BrowserWindow({
          width: SHARECARD_STAGE_WIDTH_PX,
          height: 600,
          useContentSize: true,
          show: false,
          frame: false,
          transparent: false,
          backgroundColor: '#c3cfe2',
          focusable: false,
          resizable: true,
          webPreferences: {
            preload: preloadPath,
            contextIsolation: true,
            sandbox: true,
            nodeIntegration: false,
            devTools: isDev,
            backgroundThrottling: false,
            // zoomFactor は使わない（CSS transform で拡大する）
          },
        });

        const bw = win;

        // IMPORTANT:
        // - BrowserWindow/webContents は destroy 後にプロパティ参照だけで例外を投げることがある。
        // - イベントコールバック内では webContents へ触れず、ここで固定した id を使う。
        sender = bw.webContents;
        webContentsId = sender.id;
        _ctx.security.registerWindow('share_card', sender);

        // NOTE:
        // - sharecard renderer がクラッシュ/ロード失敗した場合、ready を待ち続けて UX が悪化しないよう即時 reject する。
        try {
          const id = webContentsId;
          bw.webContents.on?.('did-fail-load', () =>
            rejectPendingReady(id, 'ShareCard failed to load.')
          );
          bw.webContents.on?.('render-process-gone', () =>
            rejectPendingReady(id, 'ShareCard renderer crashed.')
          );
          bw.on?.('closed', () => rejectPendingReady(id, 'ShareCard window closed.'));
        } catch {
          // no-op
        }

        if (urlSpec.kind === 'url') {
          await bw.loadURL(urlSpec.url);
        } else {
          await bw.loadFile(urlSpec.filePath, { query: urlSpec.query });
        }

        // content を流し込む（renderer は set-content を購読して描画する）
        try {
          bw.webContents.send('set-content', JSON.stringify(cap));
        } catch {
          // ウィンドウが破棄されている可能性
          if (webContentsId != null)
            rejectPendingReady(webContentsId, 'ShareCard window disposed.');
          return { ok: false, error: 'ShareCard window disposed.' };
        }

        // renderer(sharecard) が高さ計測して sharecard:ready を送るのを待つ
        let captureHeight = computeCaptureWindowHeight(await waitForReady(webContentsId));
        if (bw.isDestroyed()) return { ok: false, error: 'ShareCard window disposed.' };

        bw.setContentSize(
          SHARECARD_STAGE_WIDTH_PX,
          computeShareCardCapturePlan(captureHeight).viewportHeight
        );

        // レイアウト確定待ち（2フレーム）
        try {
          await bw.webContents.executeJavaScript(FINAL_LAYOUT_WAIT_SCRIPT);
        } catch {
          // no-op
        }

        // setContentSize 後に折り返し/scrollHeight が変わることがあるため、最終高さを再測定する。
        try {
          const finalMeasuredHeight = await bw.webContents.executeJavaScript(
            MEASURE_SHARECARD_HEIGHT_SCRIPT
          );
          if (typeof finalMeasuredHeight === 'number' && Number.isFinite(finalMeasuredHeight)) {
            captureHeight = Math.max(
              captureHeight,
              computeCaptureWindowHeight(finalMeasuredHeight)
            );
          }
        } catch {
          // 初回測定値で続行する
        }

        // 実描画キャプチャ。長文ではOSのウィンドウ最大高に依存せず、DevToolsの仮想viewportで全体を撮る。
        if (bw.isDestroyed()) return { ok: false, error: 'ShareCard window disposed.' };
        const captured = await captureFullShareCard(electron.nativeImage, bw, captureHeight);
        const capturedSize = captured.getSize();

        // 通常Overlayと同じ縦横比を維持したまま、1600px幅にアップスケール
        // (Retinaディスプレイでは capturePage が2x密度で取得するので、ある程度の解像度は確保される)
        const { width: finalWidth, height: finalHeight } = computeResize(capturedSize);

        const finalImage = captured.resize({
          width: finalWidth,
          height: finalHeight,
          quality: 'best',
        });

        const pngBytes = finalImage.toPNG();
        const filename = `pantaray-${formatShareTimestamp(new Date())}.png`;

        // Clipboard
        let clipboardOk = false;
        try {
          electron.clipboard.writeImage(finalImage);
          clipboardOk = true;
        } catch {
          clipboardOk = false;
        }

        // Downloads
        const saveRes = await savePngToDownloads(electron.app, pngBytes, filename);
        const downloadOk = saveRes.ok;

        if (clipboardOk || downloadOk) {
          return {
            ok: true,
            clipboardOk,
            downloadOk,
            filename,
            path: saveRes.ok ? saveRes.path : undefined,
          };
        }
        return { ok: false, error: saveRes.ok ? 'Failed to write clipboard.' : saveRes.error };
      } catch (e) {
        return {
          ok: false,
          error: e instanceof Error ? e.message : 'Failed to capture sharecard.',
        };
      } finally {
        try {
          // waitForReady が動いている可能性があるため、ここでも best-effort で解除する
          if (typeof webContentsId === 'number') {
            rejectPendingReady(webContentsId, 'ShareCard window disposed.');
          }
          if (sender) {
            _ctx.security.unregisterWindow(sender);
          }
          if (win && !win.isDestroyed()) {
            win.destroy();
          }
        } catch {
          // no-op
        }
      }
    }
  );
}

// テスト用の公開（実運用コードからは参照しない）
export const __test__ = {
  normalizeCapturePayload,
  normalizeReadyPayload,
  computeResize,
  computeCaptureWindowHeight,
  computeShareCardCapturePlan,
  formatShareTimestamp,
};
