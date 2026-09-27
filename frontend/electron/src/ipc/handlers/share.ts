/**
 * share:* IPC handlers
 *
 * 目的:
 * - AgentOverlay の「共有スクリーンショット（共有カード）」を Downloads に安全に保存できるようにする。
 *
 * セキュリティ方針:
 * - 保存先は main 側で固定（`app.getPath('downloads')`）
 * - `filename` は strict に検証（`pantaray-YYYYMMDD-HHMMSS-SSS.png` のみ許可）
 * - `pngBytes` は型とサイズ、PNGシグネチャを検証（fail-closed）
 */

import { promises as fs } from 'node:fs';
import path from 'node:path';

import type { MainContext } from '../context';
import type { IpcRegistrar } from '../registrar';

// NOTE: 正規表現リテラル内では `\.` と書く（文字列ではないため二重エスケープは不要）
const FILENAME_RE = /^pantaray-[0-9]{8}-[0-9]{6}-[0-9]{3}\.png$/;
const MAX_PNG_BYTES = 25 * 1024 * 1024; // 25MB（十分な余裕を持たせつつDoSを抑える）

type SavePngResult = { ok: true; path: string } | { ok: false; error: string };

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object';
}

function normalizeFilename(raw: unknown): string | null {
  if (typeof raw !== 'string') return null;
  const name = raw.trim();
  if (!FILENAME_RE.test(name)) return null;
  return name;
}

function normalizeBytes(raw: unknown): Uint8Array | null {
  if (!raw) return null;

  // Uint8Array / Buffer
  if (raw instanceof Uint8Array) return raw;

  // ArrayBuffer
  if (raw instanceof ArrayBuffer) return new Uint8Array(raw);

  // number[]
  if (Array.isArray(raw) && raw.every((v) => Number.isInteger(v) && v >= 0 && v <= 255)) {
    // DoS耐性: 先に長さで弾く（`every` は O(n) のため）
    if (raw.length > MAX_PNG_BYTES) return null;
    try {
      return Uint8Array.from(raw);
    } catch {
      return null;
    }
  }

  return null;
}

function isPng(bytes: Uint8Array): boolean {
  // PNG signature: 89 50 4E 47 0D 0A 1A 0A
  if (bytes.length < 8) return false;
  return (
    bytes[0] === 0x89 &&
    bytes[1] === 0x50 &&
    bytes[2] === 0x4e &&
    bytes[3] === 0x47 &&
    bytes[4] === 0x0d &&
    bytes[5] === 0x0a &&
    bytes[6] === 0x1a &&
    bytes[7] === 0x0a
  );
}

function resolveDownloadsPath(filename: string): string | null {
  try {
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    const { app } = require('electron') as { app: { getPath: (name: string) => string } };
    const downloadsDir = app.getPath('downloads');
    if (!downloadsDir) return null;
    return path.join(downloadsDir, filename);
  } catch {
    return null;
  }
}

function sanitizeSaveError(e: unknown): string {
  const code = isRecord(e) ? e.code : null;
  if (code === 'EEXIST') return 'File already exists.';
  if (code === 'EACCES' || code === 'EPERM') return 'Permission denied.';
  if (code === 'ENOENT') return 'Downloads folder not found.';
  return 'Failed to save PNG.';
}

export function registerShareHandlers(_ctx: MainContext, registrar: IpcRegistrar): void {
  registrar.handle('share:savePng', async (_evt, payload: unknown): Promise<SavePngResult> => {
    try {
      const p = isRecord(payload) ? payload : null;
      const filename = normalizeFilename(p?.filename);
      const bytes = normalizeBytes(p?.pngBytes);

      if (!filename) {
        return { ok: false, error: 'Invalid filename.' };
      }
      if (!bytes) {
        return { ok: false, error: 'Invalid png bytes.' };
      }
      if (bytes.length > MAX_PNG_BYTES) {
        return { ok: false, error: 'PNG is too large.' };
      }
      if (!isPng(bytes)) {
        return { ok: false, error: 'Invalid PNG signature.' };
      }

      const outPath = resolveDownloadsPath(filename);
      if (!outPath) {
        return { ok: false, error: 'Failed to resolve Downloads path.' };
      }

      // 既存ファイル上書きはしない（timestamp前提）
      await fs.writeFile(outPath, bytes, { flag: 'wx' });
      return { ok: true, path: outPath };
    } catch (e) {
      return { ok: false, error: sanitizeSaveError(e) };
    }
  });
}
