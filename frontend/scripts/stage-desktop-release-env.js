const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const dotenv = require('dotenv');
const { buildRuntimeConfig } = require('./generate-electron-runtime-config');
const { buildLocalBackendRuntimeBundle } = require('../electron/local_backend_runtime_bundle');

// Runner-owned inputs live outside checkout so actions/checkout cannot delete them.
function stageDesktopReleaseEnv(sourceDir, repoRoot) {
  const files = ['frontend/.env.production', 'agents/.env.local.backend.production'];
  const contents = files.map((file) => {
    const source = path.join(sourceDir, file);
    if (!fs.existsSync(source)) {
      throw new Error(`Missing desktop release environment file: ${source}`);
    }
    return fs.readFileSync(source, 'utf8');
  });

  // Validate both inputs before changing checkout; never print their contents.
  buildRuntimeConfig({ ...dotenv.parse(contents[0]), PANTARAY_RELEASE_BUILD: '1' });
  buildLocalBackendRuntimeBundle(dotenv.parse(contents[1]), { releaseBuild: true });

  for (const [index, file] of files.entries()) {
    const target = path.join(repoRoot, file);
    fs.writeFileSync(target, contents[index], { mode: 0o600 });
    fs.chmodSync(target, 0o600);
  }
}

if (require.main === module) {
  stageDesktopReleaseEnv(
    path.join(os.homedir(), '.config', 'pantaray', 'desktop-release'),
    process.cwd()
  );
}

module.exports = { stageDesktopReleaseEnv };
