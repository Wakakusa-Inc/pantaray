/**
 * Electron main bootstrap
 *
 * 目的:
 * - Electron(main) をTypeScriptへ段階移行するため、まず `electron/dist/main.js` を優先して読み込む。
 * - dist が未生成の環境では fail-fast し、開発者にビルド手順を促す。
 *
 * セキュリティ方針:
 * - このファイル自体は機密情報をログ出力しない。
 */

const fs = require('fs');
const path = require('path');

const distMainPath = path.join(__dirname, 'dist', 'main.js');

function safeRequire(targetPath) {
  // eslint-disable-next-line global-require, import/no-dynamic-require
  return require(targetPath);
}

if (!fs.existsSync(distMainPath)) {
  const msg =
    '[pantaray] electron/dist/main.js が見つかりません。' +
    ' 先に Electron(main) をビルドしてください: `npm run build:electron`（または `./node_modules/.bin/tsc -p electron/tsconfig.json`）';
  try {
    // eslint-disable-next-line no-console
    console.error(msg);
  } catch {
    // no-op
  }
  throw new Error(msg);
}

try {
  safeRequire(distMainPath);
} catch (err) {
  // dist が存在するのに起動できないのは致命（移設後は legacy fallback しない）
  try {
    // eslint-disable-next-line no-console
    console.error('[pantaray] Failed to load electron/dist/main.js.', {
      message: err instanceof Error ? err.message : String(err),
    });
  } catch {
    // no-op
  }
  throw err;
}
