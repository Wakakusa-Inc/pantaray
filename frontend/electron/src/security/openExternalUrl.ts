/**
 * External URL opener（renderer → main）
 *
 * 目的:
 * - `electron/src/main.ts` から外部URL open の処理を切り出し、main の責務を薄くする。
 * - policy に従い fail-closed でブロックし、必要なら監査ログを残す（既存挙動維持）。
 */

import { shell } from 'electron';

import { validateExternalUrl } from './externalUrlPolicy';

type LoggerLike = {
  warn?: (name: string, payload?: unknown) => void;
  info?: (name: string, payload?: unknown) => void;
  safeUrlSummary?: (url: string) => unknown;
  fingerprint?: (value: unknown) => string;
};

export function createExternalUrlOpener(params: {
  isDevRuntime: () => boolean;
  webAppOrigin: string | null;
  logger: LoggerLike | null;
}): (rawUrl: unknown) => Promise<void> {
  return async function openExternalUrlFromRenderer(rawUrl: unknown): Promise<void> {
    try {
      const res = validateExternalUrl(rawUrl, {
        isDev: params.isDevRuntime(),
        webAppOrigin: params.webAppOrigin || null,
      });
      if (!res || res.ok !== true) {
        try {
          params.logger?.warn?.('EXTERNAL_URL_BLOCKED', {
            ok: false,
            reason:
              res && 'reason' in res
                ? String((res as { reason?: unknown }).reason || 'unknown')
                : 'unknown',
            url:
              typeof rawUrl === 'string'
                ? params.logger?.safeUrlSummary?.(rawUrl)
                : { type: typeof rawUrl },
            policy: {
              mode: 'web_app_origin',
              web_app_origin: params.webAppOrigin
                ? params.logger?.safeUrlSummary?.(params.webAppOrigin)
                : null,
            },
          });
        } catch {
          // no-op
        }
        return;
      }

      await shell.openExternal(res.url);
      try {
        params.logger?.info?.('EXTERNAL_URL_OPENED', {
          ok: true,
          url: params.logger?.safeUrlSummary?.(res.url),
        });
      } catch {
        // no-op
      }
    } catch (error) {
      try {
        params.logger?.warn?.('EXTERNAL_URL_OPEN_ERR', {
          ok: false,
          err: error,
          url:
            typeof rawUrl === 'string'
              ? params.logger?.safeUrlSummary?.(rawUrl)
              : { type: typeof rawUrl },
        });
      } catch {
        // no-op
      }
    }
  };
}
