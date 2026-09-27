const assert = require('node:assert/strict');
const fs = require('node:fs');
const { execFileSync } = require('node:child_process');
const os = require('node:os');
const path = require('node:path');
const test = require('node:test');

const BACKEND_ENV = 'agents/.env.local.backend.production';

test('the checked-in release inputs alone generate both packaged configurations', (t) => {
  const checkout = fs.mkdtempSync(path.join(os.tmpdir(), 'desktop-release-env-'));
  t.after(() => fs.rmSync(checkout, { recursive: true, force: true }));
  fs.mkdirSync(path.join(checkout, 'agents'));
  fs.copyFileSync(path.resolve(__dirname, '../..', BACKEND_ENV), path.join(checkout, BACKEND_ENV));
  // Run the actual build entrypoints in an isolated checkout, without ambient app settings.
  const frontend = path.join(checkout, 'frontend');
  for (const file of [
    '.env.production',
    'scripts/generate-electron-runtime-config.js',
    'scripts/prepare-local-backend-runtime-bundle.js',
    'scripts/runtime-build-env.js',
    'electron/local_backend_runtime_bundle.js',
    'electron/loopback_backend_url.js',
    'electron/src/auth/accountLoginFeature.ts',
  ]) {
    const dest = path.join(frontend, file);
    fs.mkdirSync(path.dirname(dest), { recursive: true });
    fs.copyFileSync(path.resolve(__dirname, '..', file), dest);
  }
  fs.symlinkSync(path.resolve(__dirname, '../node_modules'), path.join(frontend, 'node_modules'));
  for (const script of [
    'generate-electron-runtime-config',
    'prepare-local-backend-runtime-bundle',
  ]) {
    execFileSync(process.execPath, [path.join(frontend, 'scripts', `${script}.js`)], {
      env: { PANTARAY_RELEASE_BUILD: '1' },
    });
  }
  const config = JSON.parse(fs.readFileSync(path.join(frontend, 'electron/runtime_config.json')));
  const bundle = JSON.parse(
    fs.readFileSync(path.join(frontend, 'electron/resources/local_backend_runtime.bundle.json'))
  );
  // Account login is off: no account portal, Supabase or Cloud proxy settings ship.
  assert.deepEqual(Object.keys(config).sort(), ['api_host_origin', 'backend_url']);
  assert.equal('LLM_PROXY_URL' in bundle, false);
  assert.equal('WEB_TOOLS_PROXY_URL' in bundle, false);
  assert.equal(bundle.NODE_ENV, 'production');
});
