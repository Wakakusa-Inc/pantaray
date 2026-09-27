import { test, expect } from '@playwright/test';
import { launchElectronE2E } from './harness';

// eslint-disable-next-line no-empty-pattern
test('履歴の削除は main を通って local backend に届き、もう無い会話も削除済みになる', async ({}, testInfo) => {
  const { harness, stop } = await launchElectronE2E();
  try {
    const { page } = harness;
    await page.waitForURL(/#\/history$/);
    // preload → IPC → main → route allowlist → local backend, answered 204 with no body. The
    // page can show before the local runtime is ready, and deleting is idempotent, so it polls.
    await expect
      .poll(() =>
        page.evaluate(() =>
          window.electron?.history?.deleteItem({ kind: 'conversation', id: 'e2e-missing-action' })
        )
      )
      .toEqual({ ok: true });
  } finally {
    await stop({ keepArtifacts: testInfo.status !== testInfo.expectedStatus });
  }
});
