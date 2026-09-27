import { defineConfig } from '@playwright/test';

// Electron UI E2E 専用の設定。
// - vitest は `src/**`、node --test は `tests/*.test.js` を対象にしており、
//   `tests/e2e/**/*.spec.ts` はどちらの include にも一致しない（衝突しない）。
// - Electron はグローバル資源（loopback auth port 32100 / 単一アプリ）を使うため直列固定。
export default defineConfig({
  testDir: './tests/e2e',
  fullyParallel: false,
  workers: 1,
  // 初回はローカル backend（uv run）と Vite dev server のコールドスタートを含むため長め。
  timeout: 240_000,
  expect: { timeout: 30_000 },
  reporter: [['list']],
  outputDir: './test-results',
  use: {
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
});
