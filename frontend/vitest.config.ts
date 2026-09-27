import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';
import path from 'path';

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  test: {
    // Vitest は React/renderer 側（src配下）のみを対象にする
    // - Electron(main) の node:test（frontend/tests/*）は node --test で実行する
    include: ['src/**/*.{test,spec}.{ts,tsx}'],
    exclude: ['tests/**', '**/node_modules/**'],
    // jsdom は依存ツリー内で CJS→ESM require が発生しやすいため、happy-dom を採用する
    environment: 'happy-dom',
    setupFiles: ['./src/tests/setup.ts'],
    // CI/ツール実行でのハング・タイムアウトを避けるため、並列度を落とす
    pool: 'threads',
    maxWorkers: 1,
    fileParallelism: false,
    silent: true,
  },
});
