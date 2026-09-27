const assert = require('node:assert/strict');
const fs = require('node:fs');
const { execFileSync } = require('node:child_process');
const os = require('node:os');
const path = require('node:path');
const test = require('node:test');
const { stageDesktopReleaseEnv } = require('../scripts/stage-desktop-release-env');

const FRONTEND_ENV = `BACKEND_URL=http://127.0.0.1:8005
VITE_API_HOST=http://127.0.0.1:8005
VITE_WEB_APP_URL=https://account.example.test
VITE_SUPABASE_URL=https://example.supabase.co
VITE_SUPABASE_PUBLISHABLE_KEY=public-test-key
`;
const BACKEND_ENV = `USE_MOCKS=false
ALLOWED_ORIGINS=http://127.0.0.1:8005
ALLOWED_HOSTS=127.0.0.1
LOCAL_DB_BUSY_TIMEOUT_MS=5000
LLM_PROXY_URL=https://api.example.test/v1/llm/proxy
WEB_TOOLS_PROXY_URL=https://api.example.test/v1/web-search/proxy
`;
const FILES = ['frontend/.env.production', 'agents/.env.local.backend.production'];

function setup(t) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'desktop-release-env-'));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  const source = path.join(root, 'runner-config');
  const checkout = path.join(root, 'checkout');
  for (const base of [source, checkout]) {
    for (const dir of ['frontend', 'agents']) {
      fs.mkdirSync(path.join(base, dir), { recursive: true });
    }
  }
  fs.writeFileSync(path.join(source, FILES[0]), FRONTEND_ENV);
  fs.writeFileSync(path.join(source, FILES[1]), BACKEND_ENV);
  return { source, checkout };
}

test('staged local inputs generate both packaged configurations without AWS', (t) => {
  const { source, checkout } = setup(t);
  // A reused checkout must not retain a world-readable mode from an earlier run.
  fs.writeFileSync(path.join(checkout, FILES[0]), 'stale', { mode: 0o644 });
  stageDesktopReleaseEnv(source, checkout);
  // Run the actual build entrypoints in an isolated checkout, without ambient app settings.
  const frontend = path.join(checkout, 'frontend');
  for (const file of [
    'scripts/generate-electron-runtime-config.js',
    'scripts/prepare-local-backend-runtime-bundle.js',
    'scripts/runtime-build-env.js',
    'electron/local_backend_runtime_bundle.js',
    'electron/loopback_backend_url.js',
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
  assert.equal(config.web_app_origin, 'https://account.example.test');
  assert.equal(bundle.LLM_PROXY_URL, 'https://api.example.test/v1/llm/proxy');
  assert.equal(bundle.NODE_ENV, 'production');
  for (const file of FILES) {
    const target = path.join(checkout, file);
    assert.equal(fs.readFileSync(target, 'utf8'), fs.readFileSync(path.join(source, file), 'utf8'));
    assert.equal(fs.statSync(target).mode & 0o777, 0o600);
    fs.unlinkSync(target);
    assert.ok(fs.existsSync(path.join(source, file)));
  }
});

test('missing backend input fails before staging the frontend', (t) => {
  const { source, checkout } = setup(t);
  fs.unlinkSync(path.join(source, FILES[1]));
  assert.throws(
    () => stageDesktopReleaseEnv(source, checkout),
    /Missing desktop release environment file/
  );
  assert.equal(fs.existsSync(path.join(checkout, FILES[0])), false);
});

for (const [file, contents, error] of [
  [
    FILES[0],
    FRONTEND_ENV.replace('VITE_SUPABASE_PUBLISHABLE_KEY=public-test-key\n', ''),
    /VITE_SUPABASE_PUBLISHABLE_KEY/,
  ],
  [
    FILES[0],
    FRONTEND_ENV.replace(
      'VITE_API_HOST=http://127.0.0.1:8005',
      'VITE_API_HOST=http://127.0.0.1:8006'
    ),
    /must match/,
  ],
  [FILES[1], BACKEND_ENV.replace('USE_MOCKS=false\n', ''), /USE_MOCKS/],
]) {
  test(`invalid ${file} fails before replacing either checkout input: ${error}`, (t) => {
    const { source, checkout } = setup(t);
    fs.writeFileSync(path.join(source, file), contents);
    assert.throws(() => stageDesktopReleaseEnv(source, checkout), error);
    for (const target of FILES) assert.equal(fs.existsSync(path.join(checkout, target)), false);
  });
}
